"""Same-origin streaming relay for authenticated PDF previews."""

from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Path, Request, Response
from nicegui import app
from starlette.responses import StreamingResponse

from .config import api_url

router = APIRouter(include_in_schema=False)
Checksum = Annotated[str, Path(pattern="^[0-9a-f]{64}$")]
RESPONSE_HEADERS = (
    "accept-ranges",
    "content-range",
    "content-type",
    "content-length",
    "content-disposition",
    "etag",
    "content-security-policy",
    "x-content-type-options",
)


async def upstream_client():
    # Request-scoped teardown also runs when PDF.js cancels its initial GET.
    async with httpx.AsyncClient(base_url=api_url(), timeout=httpx.Timeout(30, connect=5)) as client:
        yield client


async def relay(request, client, path, checksum, event=None, *, converted=False):
    token = app.storage.user.get("session_token")
    headers = {"Cache-Control": "private, no-store"}
    if not token:
        return Response(status_code=401, headers=headers)
    upstream_headers = {
        "Authorization": f"Bearer {token}",
        "If-Match": f'"sha256-{checksum}"',
        "Accept-Encoding": "identity",
        "X-Event-Source": "web_ui",
    }
    if event is not None:
        upstream_headers["X-Wathiq-Converted-PDF" if converted else "X-Wathiq-Preview-Event"] = str(event)
    if "range" in request.headers:
        upstream_headers["Range"] = request.headers["range"]
    try:
        upstream = await client.send(
            client.build_request(request.method, path, headers=upstream_headers), stream=True
        )
    except httpx.RequestError:
        return Response(status_code=502, headers=headers)
    if upstream.is_error:
        if "content-range" in upstream.headers:
            headers["Content-Range"] = upstream.headers["content-range"]
        return Response(status_code=upstream.status_code, headers=headers)
    headers.update({key: upstream.headers[key] for key in RESPONSE_HEADERS if key in upstream.headers})
    # Preserve byte offsets through compression middleware and reverse proxies.
    headers.update({"Content-Encoding": "identity", "X-Accel-Buffering": "no"})
    if request.method in {"HEAD", "DELETE"}:
        return Response(status_code=upstream.status_code, headers=headers)
    return StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code, headers=headers)


@router.api_route("/preview-pdf/records/{component_id}/{checksum}/{event}", methods=["GET", "HEAD"])
async def saved_pdf(
    request: Request,
    component_id: int,
    checksum: Checksum,
    event: UUID,
    client: httpx.AsyncClient = Depends(upstream_client, scope="request"),
):
    return await relay(
        request, client, f"/api/v1/digital-components/{component_id}/rendition", checksum, event
    )


@router.api_route("/preview-pdf/drafts/{draft_id}/{component_id}/{checksum}", methods=["GET", "HEAD"])
async def draft_pdf(
    request: Request,
    draft_id: int,
    component_id: int,
    checksum: Checksum,
    client: httpx.AsyncClient = Depends(upstream_client, scope="request"),
):
    path = f"/api/v1/record-drafts/{draft_id}/components/{component_id}/rendition"
    return await relay(request, client, path, checksum)


@router.api_route("/preview-pdf/converted/records/{component_id}/{checksum}/{event}", methods=["GET", "HEAD", "DELETE"])
async def converted_saved_pdf(
    request: Request, component_id: int, checksum: Checksum, event: UUID,
    client: httpx.AsyncClient = Depends(upstream_client, scope="request"),
):
    path = f"/api/v1/digital-components/{component_id}/rendition"
    return await relay(request, client, path, checksum, event, converted=True)


@router.api_route("/preview-pdf/converted/drafts/{draft_id}/{component_id}/{checksum}/{event}", methods=["GET", "HEAD", "DELETE"])
async def converted_draft_pdf(
    request: Request, draft_id: int, component_id: int, checksum: Checksum, event: UUID,
    client: httpx.AsyncClient = Depends(upstream_client, scope="request"),
):
    path = f"/api/v1/record-drafts/{draft_id}/components/{component_id}/rendition"
    return await relay(request, client, path, checksum, event, converted=True)
