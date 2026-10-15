from __future__ import annotations

import asyncio
import copy
import inspect
import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(self.message)

    @property
    def message(self) -> str:
        if isinstance(self.detail, dict):
            return str(self.detail.get("message", self.detail))
        return str(self.detail)


class ErmsApiClient:
    _REFERENCE_RESOURCES = {
        "classification-schemes", "org-units", "privileges", "profiles",
        "roles", "security-levels",
    }

    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(30, connect=5),
            transport=transport,
        )
        # A page can load dashboard cards and navigation counts concurrently.
        # Keep that burst comfortably below the API's default database pool size.
        self._request_slots = asyncio.Semaphore(4)
        self._inflight_reads: dict[str, asyncio.Task[Any]] = {}
        self._reference_cache: dict[str, dict[str, Any]] = {}
        self._session_token: str | None = None
        self._unauthorized_handler: Callable[[], Any] | None = None

    def set_session_token(self, token: str | None) -> None:
        """Keep authentication attached to this browser page's API client."""
        if token != self._session_token:
            self.clear_reference_cache()
        self._session_token = token

    def clear_reference_cache(self) -> None:
        """Discard identity-scoped reference rows after identity/data changes."""
        self._reference_cache.clear()

    def cancel_pending_reads(self) -> None:
        """Stop reads belonging to a page transition the user abandoned."""
        for task in tuple(self._inflight_reads.values()):
            if not task.done():
                task.cancel()

    def set_unauthorized_handler(self, handler: Callable[[], Any]) -> None:
        self._unauthorized_handler = handler

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        with_metadata = bool(kwargs.pop("_with_metadata", False))
        cancellable_read = bool(kwargs.pop("_cancellable_read", False))
        headers = dict(kwargs.pop("headers", {}))
        # httpx defaults string header values to ASCII. Reasons are human text;
        # send their UTF-8 bytes while leaving ordinary ASCII headers unchanged.
        for name, value in list(headers.items()):
            if name.lower() == "x-change-reason" and isinstance(value, str):
                headers[name] = value.encode("utf-8")
        headers.setdefault("X-Event-Source", "web_ui")
        if self._session_token:
            headers.setdefault("Authorization", f"Bearer {self._session_token}")
        kwargs["headers"] = headers
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD"}:
            # Reference lists are intentionally broad: any successful or failed
            # mutation may affect labels, eligibility, status, or authorization.
            self.clear_reference_cache()
        if normalized_method in {"GET", "HEAD"}:
            # Independent components often need the same reference data while a
            # page is rendering. Share the in-flight HTTP operation, but return
            # a private result because callers decorate response dictionaries.
            request_key = json.dumps(
                [normalized_method, path, kwargs, with_metadata],
                sort_keys=True, default=str,
                separators=(",", ":"),
            )
            task = self._inflight_reads.get(request_key)
            if task is None:
                task = asyncio.create_task(
                    self._perform_request(
                        normalized_method, path, kwargs,
                        with_metadata=with_metadata,
                    )
                )
                self._inflight_reads[request_key] = task
                task.add_done_callback(
                    lambda completed, key=request_key: self._finish_inflight_read(
                        key, completed,
                    )
                )
            return copy.deepcopy(await task if cancellable_read else await asyncio.shield(task))
        return await self._perform_request(
            normalized_method, path, kwargs, with_metadata=with_metadata,
        )

    def _finish_inflight_read(
        self, request_key: str, task: asyncio.Task[Any],
    ) -> None:
        if self._inflight_reads.get(request_key) is task:
            self._inflight_reads.pop(request_key, None)
        if not task.cancelled():
            task.exception()  # mark an unobserved failure as retrieved

    async def _perform_request(
        self, method: str, path: str, kwargs: dict[str, Any], *,
        with_metadata: bool = False,
    ) -> Any:
        try:
            async with self._request_slots:
                response = await self._client.request(method, path, **kwargs)
        except RuntimeError as error:
            if self._client.is_closed:
                raise ApiError(503, "The browser session disconnected from the ERMS API") from error
            raise
        except httpx.HTTPError as error:
            raise ApiError(503, "Cannot connect to the ERMS API") from error
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text or response.reason_phrase
            if response.status_code == 401 and self._unauthorized_handler:
                result = self._unauthorized_handler()
                if inspect.isawaitable(result):
                    await result
            raise ApiError(response.status_code, detail)
        if response.status_code in {204, 304}:
            payload = None
        else:
            content_type = response.headers.get("content-type", "")
            is_attachment = response.headers.get("content-disposition", "").lower().startswith("attachment")
            payload = response.json() if "json" in content_type and not is_attachment else response.content
        if with_metadata:
            return {
                "status_code": response.status_code,
                "etag": response.headers.get("etag"),
                "payload": payload,
            }
        return payload

    async def _reference_get(
        self, cache_key: str, path: str, *, params: dict[str, Any],
    ) -> Any:
        cached = self._reference_cache.get(cache_key)
        if cached and time.monotonic() - cached["checked_at"] < 30:
            return copy.deepcopy(cached["value"])
        headers = {"If-None-Match": cached["etag"]} if cached and cached.get("etag") else {}
        result = await self.request(
            "GET", path, params=params, headers=headers, _with_metadata=True,
        )
        if result["status_code"] == 304 and cached:
            cached["checked_at"] = time.monotonic()
            return copy.deepcopy(cached["value"])
        entry = {
            "value": result["payload"], "etag": result.get("etag"),
            "checked_at": time.monotonic(),
        }
        self._reference_cache[cache_key] = entry
        return copy.deepcopy(entry["value"])

    async def login(self, email: str, password: str, *, user_agent: str | None = None) -> tuple[dict[str, Any], str]:
        async with httpx.AsyncClient(
            base_url=str(self._client.base_url), timeout=30, transport=self._transport
        ) as client:
            response = await client.post(
                "/api/v1/auth/login", json={"email": email, "password": password},
                headers={
                    "X-Event-Source": "web_ui",
                    **({"User-Agent": user_agent} if user_agent else {}),
                },
            )
        if response.is_error:
            raise ApiError(response.status_code, response.json().get("detail", "login failed"))
        token = response.cookies.get("erms_session")
        if not token:
            raise ApiError(500, "authentication service did not issue a session")
        return response.json(), token

    async def me(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/auth/me")

    async def localization_bootstrap(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/i18n/bootstrap")

    async def localization_catalogue(
        self, language_tag: str, *, etag: str | None = None,
    ) -> dict[str, Any]:
        headers = {"If-None-Match": etag} if etag else {}
        headers["X-Event-Source"] = "web_ui"
        if self._session_token:
            headers["Authorization"] = f"Bearer {self._session_token}"
        try:
            async with self._request_slots:
                response = await self._client.get(
                    f"/api/v1/i18n/catalogues/{language_tag}", headers=headers,
                )
        except RuntimeError as error:
            if self._client.is_closed:
                raise ApiError(503, "The browser session disconnected from the ERMS API") from error
            raise
        except httpx.HTTPError as error:
            raise ApiError(503, "Cannot connect to the ERMS API") from error
        if response.status_code == 304:
            return {"not_modified": True, "etag": response.headers.get("etag") or etag}
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text or response.reason_phrase
            if response.status_code == 401 and self._unauthorized_handler:
                result = self._unauthorized_handler()
                if inspect.isawaitable(result):
                    await result
            raise ApiError(response.status_code, detail)
        payload = response.json()
        payload["etag"] = response.headers.get("etag")
        payload["not_modified"] = False
        return payload

    async def localization_languages(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/api/v1/admin/i18n/languages")

    async def create_localization_language(
        self, payload: dict[str, Any], reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", "/api/v1/admin/i18n/languages", json=payload,
            headers={"X-Change-Reason": reason},
        )

    async def update_localization_language(
        self, language_tag: str, payload: dict[str, Any], version: int, reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "PUT", f"/api/v1/admin/i18n/languages/{language_tag}", json=payload,
            headers={"If-Match": str(version), "X-Change-Reason": reason},
        )

    async def localization_messages(self, **params: Any) -> dict[str, Any]:
        # httpx serializes ``None`` query values as empty strings.  FastAPI
        # correctly rejects an empty string for the optional boolean filter,
        # so omit inactive filters instead of sending ``needs_attention=``.
        return await self.request(
            "GET",
            "/api/v1/admin/i18n/messages",
            params={key: value for key, value in params.items() if value is not None},
        )

    async def update_localization_translation(
        self, message_key: str, language_tag: str, payload: dict[str, Any], version: int, reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "PUT", f"/api/v1/admin/i18n/messages/{message_key}/translations/{language_tag}",
            json=payload, headers={"If-Match": str(version), "X-Change-Reason": reason},
        )

    async def publish_localization_translation(
        self, message_key: str, language_tag: str, version: int, reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/admin/i18n/messages/{message_key}/translations/{language_tag}/publish",
            headers={"If-Match": str(version), "X-Change-Reason": reason},
        )

    async def localization_generation_report(self, language_tag: str) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/admin/i18n/generation-report/{language_tag}"
        )

    async def preview_bulk_localization_publication(
        self, language_tag: str, context_group: str = "",
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/admin/i18n/translations/{language_tag}/bulk-publication-preview",
            params={"context_group": context_group} if context_group else None,
        )

    async def bulk_review_publish_localization(
        self, language_tag: str, items: list[dict[str, Any]], reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/admin/i18n/translations/{language_tag}/bulk-review-publish",
            json={"items": items}, headers={"X-Change-Reason": reason},
        )

    async def store_generated_localization_drafts(
        self, language_tag: str, payload: dict[str, Any], reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/admin/i18n/generated-drafts/{language_tag}",
            json=payload, headers={"X-Change-Reason": reason},
        )

    async def preview_localization_export(
        self, language_tag: str, *, include_reviewed_drafts: bool = False,
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/admin/i18n/translations/{language_tag}/export-preview",
            params={"include_reviewed_drafts": include_reviewed_drafts},
        )

    async def export_localization_artifact(
        self, language_tag: str, *, include_reviewed_drafts: bool = False,
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/admin/i18n/translations/{language_tag}/export",
            params={"include_reviewed_drafts": include_reviewed_drafts},
        )

    async def preview_localization_import(
        self, language_tag: str, artifact: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/admin/i18n/translations/{language_tag}/import-preview",
            json={"artifact": artifact},
        )

    async def import_localization_artifact(
        self, language_tag: str, artifact: dict[str, Any], reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/admin/i18n/translations/{language_tag}/import",
            json={"artifact": artifact}, headers={"X-Change-Reason": reason},
        )

    async def preferences(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/preferences")

    async def update_preferences(
        self, language_tag: str, working_timezone: str, version: int,
    ) -> dict[str, Any]:
        return await self.request(
            "PUT", "/api/v1/preferences",
            json={"language_tag": language_tag, "working_timezone": working_timezone},
            headers={"If-Match": str(version)},
        )

    async def entity_translation(
        self, entity_type: str, entity_id: int, language_tag: str,
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/entity-translations/{entity_type}/{entity_id}/{language_tag}"
        )

    async def update_entity_translation(
        self, entity_type: str, entity_id: int, language_tag: str,
        payload: dict[str, Any], version: int, reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "PATCH", f"/api/v1/entity-translations/{entity_type}/{entity_id}/{language_tag}",
            json=payload,
            headers={"If-Match": str(version), "X-Change-Reason": reason},
        )

    async def my_recent_activity(
        self, *, limit: int = 6, since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if since is not None:
            params["since"] = since.isoformat()
        return await self.request("GET", "/api/v1/auth/me/recent-activity", params=params)

    async def profile_references(self) -> list[dict[str, Any]]:
        cache_key = "profiles/reference?limit=500"
        return await self._reference_get(
            cache_key, "/api/v1/profiles/reference", params={"limit": 500},
        )

    async def creation_role_options(
        self, parent_aggregation_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params = (
            {"parent_aggregation_id": parent_aggregation_id}
            if parent_aggregation_id is not None else None
        )
        return await self.request("GET", "/api/v1/creation-role-options", params=params)

    async def logout(self) -> None:
        await self.request("POST", "/api/v1/auth/logout")

    async def change_password(self, current_password: str, new_password: str) -> None:
        await self.request("POST", "/api/v1/auth/change-password", json={"current_password": current_password, "new_password": new_password})

    async def login_sessions(
        self, *, user_id: int | None = None, limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = {"offset": offset}
        if user_id is not None:
            params["user_id"] = user_id
        if limit is not None:
            params["limit"] = limit
        return await self.request("GET", "/api/v1/auth/sessions", params=params)

    async def login_sessions_page(
        self, user_id: int | None = None, *, limit: int | None = 20, offset: int = 0,
        query: str = "", session_status: str = "all",
        sort_by: str = "date_created", descending: bool = True,
        date_field: str = "date_created", from_timestamp: str | None = None,
        until_timestamp: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            **({"limit":limit} if limit is not None else {}), "offset": offset, "query": query,
            "session_status": session_status, "sort_by": sort_by,
            "descending": descending, "date_field": date_field,
        }
        if user_id is not None:
            params["user_id"] = user_id
        if from_timestamp:
            params["from_timestamp"] = from_timestamp
        if until_timestamp:
            params["until_timestamp"] = until_timestamp
        return await self.request(
            "GET", "/api/v1/auth/sessions/page",
            params=params,
        )

    async def revoke_session(self, session_id: int) -> None:
        await self.request("DELETE", f"/api/v1/auth/sessions/{session_id}")

    async def revoke_user_sessions(self, user_id: int) -> None:
        await self.request("DELETE", f"/api/v1/auth/users/{user_id}/sessions")

    async def issue_temporary_password(self, user_id: int) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/auth/users/{user_id}/temporary-password")

    async def service_credentials(self, user_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/api/v1/users/{user_id}/api-credentials")

    async def create_service_credential(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/users/{user_id}/api-credentials", json=payload)

    async def rotate_service_credential(self, user_id: int, credential_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/users/{user_id}/api-credentials/{credential_id}/rotate", json=payload)

    async def revoke_service_credential(self, user_id: int, credential_id: int) -> None:
        await self.request("POST", f"/api/v1/users/{user_id}/api-credentials/{credential_id}/revoke")

    async def text_indexers(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/api/v1/text-indexers")

    async def text_indexers_health(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/text-indexers/health")

    async def text_indexer_diagnostics(
        self, *, limit: int = 10, offset: int = 0,
    ) -> dict[str, Any]:
        return await self.request(
            "GET", "/api/v1/text-indexers/diagnostics",
            params={"limit": limit, "offset": offset},
        )

    async def queue_text_indexers_backfill(self, batch_size: int) -> dict[str, Any]:
        return await self.request(
            "POST", "/api/v1/text-indexers/backfill", json={"batch_size": batch_size},
        )

    async def retry_failed_text_indexer_documents(self, batch_size: int) -> dict[str, Any]:
        return await self.request(
            "POST", "/api/v1/text-indexers/retry-failed", json={"batch_size": batch_size},
        )

    async def text_indexer(self, user_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/text-indexers/{user_id}")

    async def text_indexer_credentials(
        self, user_id: int, *, history: str = "all", limit: int = 5, offset: int = 0,
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/text-indexers/{user_id}/credentials",
            params={"history": history, "limit": limit, "offset": offset},
        )

    async def create_text_indexer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/api/v1/text-indexers", json=payload)

    async def create_text_indexer_credential(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/text-indexers/{user_id}/credentials", json=payload)

    async def rotate_text_indexer_credential(
        self, user_id: int, credential_id: int, payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/text-indexers/{user_id}/credentials/{credential_id}/rotate",
            json=payload,
        )

    async def revoke_text_indexer_credential(self, user_id: int, credential_id: int) -> None:
        await self.request(
            "POST", f"/api/v1/text-indexers/{user_id}/credentials/{credential_id}/revoke",
        )

    async def set_text_indexer_status(
        self, user_id: int, version: int, action: str,
    ) -> dict[str, Any]:
        if action not in {"activate", "suspend", "unsuspend"}:
            raise ValueError("unsupported text-indexer lifecycle action")
        return await self.request(
            "POST", f"/api/v1/text-indexers/{user_id}/{action}",
            headers={"If-Match": str(version)},
        )

    async def list(self, resource: str, *, limit: int = 500, **filters: Any) -> list[dict[str, Any]]:
        params = {"limit": limit, **filters}
        if resource not in self._REFERENCE_RESOURCES:
            return await self.request("GET", f"/api/v1/{resource}", params=params)
        cache_key = json.dumps([resource, params], sort_keys=True, default=str)
        return await self._reference_get(
            cache_key, f"/api/v1/{resource}", params=params,
        )

    async def get(self, resource: str, entity_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/{resource}/{entity_id}")

    async def favourites(self) -> dict[str, list[dict[str, Any]]]:
        return await self.request("GET", "/api/v1/favourites")

    async def favourite(self, resource: str, entity_id: int) -> None:
        if resource not in {"aggregations", "records"}:
            raise ValueError("favourites support only aggregations and records")
        await self.request("PUT", f"/api/v1/favourites/{resource}/{entity_id}")

    async def unfavourite(self, resource: str, entity_id: int) -> None:
        if resource not in {"aggregations", "records"}:
            raise ValueError("favourites support only aggregations and records")
        await self.request("DELETE", f"/api/v1/favourites/{resource}/{entity_id}")

    async def browse_schemes(
        self, query: str = "", *, limit: int = 25, offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self.request(
            "GET", "/api/v1/browse/classification-schemes",
            params={"q": query, "limit": limit, "offset": offset},
        )

    async def organization_roots(
        self, *, limit: int = 25, offset: int = 0,
        audience: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self.request(
            "GET", "/api/v1/browse/organization/roots",
            params={"limit": limit, "offset": offset, **({"audience": audience} if audience else {})},
        )

    async def organization_children(
        self, org_unit_id: int, *, include_roles: bool = True,
        limit: int = 25, unit_offset: int = 0, role_offset: int = 0,
        audience: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return await self.request(
            "GET", f"/api/v1/browse/organization/org-units/{org_unit_id}/children",
            params={
                "include_roles": str(include_roles).lower(), "limit": limit,
                "unit_offset": unit_offset, "role_offset": role_offset,
                **({"audience": audience} if audience else {}),
            },
        )

    async def organization_role_users(
        self, role_id: int, *, validity: str = "all",
        limit: int = 25, offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self.request(
            "GET", f"/api/v1/browse/organization/roles/{role_id}/users",
            params={"validity": validity, "limit": limit, "offset": offset},
        )

    async def organization_summary(self, kind: str, entity_id: int) -> dict[str, Any]:
        if kind not in {"org-units", "roles"}:
            raise ValueError("organization summaries support org-units and roles")
        return await self.request(
            "GET", f"/api/v1/browse/organization/{kind}/{entity_id}/summary",
        )

    async def search_organization(
        self, query: str, *, entity_type: str = "all", status: str = "all",
        audience: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self.request(
            "GET", "/api/v1/browse/organization/search",
            params={"query": query, "entity_type": entity_type, "status": status, **({"audience": audience} if audience else {})},
        )

    async def browse_page(
        self, path: str, *, cursor: str | None = None, query: str = "", limit: int = 50,
        owning_org_unit_id: int | None = None,
        record_creation: bool = False, digital_only: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if query:
            params["query"] = query
        if owning_org_unit_id is not None:
            params["owning_org_unit_id"] = owning_org_unit_id
        if record_creation:
            params.update(record_creation=True, digital_only=digital_only)
        return await self.request("GET", f"/api/v1/browse/{path}", params=params)

    async def history(self, resource: str, entity_id: int, *, limit: int = 200) -> list[dict[str, Any]]:
        return await self.request(
            "GET", f"/api/v1/{resource}/{entity_id}/history", params={"limit": limit}
        )

    async def permissions_catalogue(self, resource_type: str) -> list[dict[str, Any]]:
        return await self.request("GET", "/api/v1/permissions", params={"resource_type": resource_type})

    async def explain_access(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/api/v1/authorization/explain", json=payload)

    async def holds_page(self, **params: Any) -> dict[str, Any]:
        return await self.request(
            "GET", "/api/v1/holds",
            params={key: value for key, value in params.items() if value is not None and value != ""},
        )

    async def holds(self, **params: Any) -> list[dict[str, Any]]:
        return (await self.holds_page(**params))["items"]

    async def hold(self, hold_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/holds/{hold_id}")

    async def hold_people(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/api/v1/holds/people")

    async def create_hold(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/api/v1/holds", json=payload)

    async def update_hold(self, hold_id: int, version: int, payload: dict[str, Any], reason: str) -> dict[str, Any]:
        return await self.request("PATCH", f"/api/v1/holds/{hold_id}", json=payload,
                                  headers={"If-Match": str(version), "X-Change-Reason": reason})

    async def delete_hold(self, hold_id: int, version: int, reason: str) -> None:
        await self.request("DELETE", f"/api/v1/holds/{hold_id}",
                           headers={"If-Match": str(version), "X-Change-Reason": reason})

    async def hold_held_items_page(self, hold_id: int, **params: Any) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/holds/{hold_id}/held-items",
            params={key: value for key, value in params.items() if value is not None and value != ""},
        )

    async def hold_held_items(self, hold_id: int, **params: Any) -> list[dict[str, Any]]:
        return (await self.hold_held_items_page(hold_id, **params))["items"]

    async def hold_contributors(self, hold_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/api/v1/holds/{hold_id}/contributors")

    async def replace_hold_contributors(self, hold_id: int, version: int, user_ids: list[int], reason: str) -> dict[str, Any]:
        return await self.request("PUT", f"/api/v1/holds/{hold_id}/contributors",
                                  json={"user_ids": user_ids},
                                  headers={"If-Match": str(version), "X-Change-Reason": reason})

    async def hold_history(self, hold_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        return await self.request("GET", f"/api/v1/holds/{hold_id}/history", params={"limit": limit})

    async def add_hold_held_item(self, hold_id: int, resource_type: str, resource_id: int, reason: str) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/holds/{hold_id}/held-items",
                                  json={"resource_type": resource_type, "resource_id": resource_id},
                                  headers={"X-Change-Reason": reason})

    async def hold_held_item_candidates(self, hold_id: int, **params: Any) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/holds/{hold_id}/held-item-candidates",
            params={key: value for key, value in params.items() if value is not None and value != ""},
        )

    async def add_hold_held_items_bulk(
        self, hold_id: int, held_items: list[dict[str, Any]], reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/holds/{hold_id}/held-items/bulk",
            json={"held_items": held_items}, headers={"X-Change-Reason": reason},
        )

    async def remove_hold_held_item(self, hold_id: int, resource_type: str, resource_id: int, version: int, reason: str) -> None:
        await self.request("DELETE", f"/api/v1/holds/{hold_id}/held-items/{resource_type}/{resource_id}",
                           headers={"If-Match": str(version), "X-Change-Reason": reason})

    async def remove_hold_held_items_bulk(self, hold_id: int, held_items: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        return await self.request("POST",f"/api/v1/holds/{hold_id}/held-items/bulk-remove",
                                  json={"held_items":held_items},headers={"X-Change-Reason":reason})

    async def effective_holds(self, resource_type: str, resource_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/api/v1/{resource_type}s/{resource_id}/effective-holds")

    async def add_resource_to_hold(self, resource_type: str, resource_id: int, hold_id: int, reason: str) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/{resource_type}s/{resource_id}/holds",
                                  json={"hold_id": hold_id}, headers={"X-Change-Reason": reason})

    async def remove_resource_from_hold(self, resource_type: str, resource_id: int, hold_id: int, reason: str) -> dict[str, Any]:
        return await self.request("DELETE", f"/api/v1/{resource_type}s/{resource_id}/holds/{hold_id}",
                                  headers={"X-Change-Reason": reason})

    async def remove_all_direct_holds(self, resource_type: str, resource_id: int, reason: str) -> dict[str, Any]:
        return await self.request("DELETE", f"/api/v1/{resource_type}s/{resource_id}/holds",
                                  headers={"X-Change-Reason": reason})

    async def explainable_users(self, *, query: str = "", limit: int = 25, offset: int = 0) -> list[dict[str, Any]]:
        return await self.request("GET", "/api/v1/authorization/explainable-users", params={"q": query, "limit": limit, "offset": offset})

    async def governance_custody(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/authorization/governance-custody")

    async def application_configuration(self) -> dict[str, Any]:
        """One finite, uncached page/dialog snapshot from the API authority."""
        return await self.request("GET", "/api/v1/application-configuration")

    async def application_settings(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/application-settings")

    async def save_application_settings(self, changes, reason: str) -> dict[str, Any]:
        return await self.request("PUT", "/api/v1/application-settings",
                                  json={"changes": changes}, headers={"X-Change-Reason": reason})

    async def security_summary(
        self, *, hours: int = 24, start_at: str | None = None, end_at: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"hours": hours}
        if start_at:
            params["start_at"] = start_at
        if end_at:
            params["end_at"] = end_at
        return await self.request("GET", "/api/v1/security-operations/summary", params=params)

    async def security_reconciliation(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/security-operations/reconciliation")

    async def resource_acl(self, resource: str, entity_id: int) -> dict[str, Any]:
        result = await self.request("GET", f"/api/v1/{resource}/{entity_id}/permissions")
        # Normalize the resource endpoint's explicit effective-source names to
        # the common source keys consumed by ACL presentation components.
        result["source"] = result.get("effective_acl_source")
        result["source_resource_id"] = result.get("effective_acl_source_id")
        return result

    async def resource_capabilities(self, resource: str, entity_id: int) -> dict[str, bool]:
        response = await self.request(
            "GET", f"/api/v1/{resource}/{entity_id}/capabilities",
        )
        return response["capabilities"]

    async def change_vital_status(self, resource: str, entity_id: int, version: int, is_vital: bool, reason: str) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/{resource}/{entity_id}/vital-status",
            json={"is_vital": is_vital, "reason": reason}, headers={"If-Match": str(version)},
        )

    async def change_review_date(self, resource: str, entity_id: int, version: int, date_of_next_review: str | None, reason: str) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/{resource}/{entity_id}/review-date",
            json={"date_of_next_review": date_of_next_review, "reason": reason},
            headers={"If-Match": str(version)},
        )

    async def change_aggregation_location(self, entity_id: int, version: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/aggregations/{entity_id}/location", json=payload, headers={"If-Match": str(version)})

    async def preview_aggregation_location(self, entity_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/aggregations/{entity_id}/location-preview", json=payload)

    async def acl_move_preview(
        self, resource: str, entity_id: int, destination_aggregation_id: int,
        *, keep_current_access_as_override: bool = False,
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/{resource}/{entity_id}/acl-move-preview",
            params={
                "destination_aggregation_id": destination_aggregation_id,
                "keep_current_access_as_override": str(keep_current_access_as_override).lower(),
            },
        )

    async def move_with_acl(
        self, resource: str, entity_id: int, payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/{resource}/{entity_id}/acl-move", json=payload,
        )

    async def ownership_correction_options(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/api/v1/ownership-correction-options")

    async def ownership_correction_preview(
        self, aggregation_id: int, destination_role_id: int,
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/aggregations/{aggregation_id}/ownership-correction-preview",
            params={"destination_role_id": destination_role_id},
        )

    async def correct_ownership(
        self, aggregation_id: int, destination_role_id: int, reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/aggregations/{aggregation_id}/correct-ownership",
            json={"destination_role_id": destination_role_id, "reason": reason},
        )

    async def replace_resource_acl(self, resource: str, entity_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PUT", f"/api/v1/{resource}/{entity_id}/permissions", json=payload)

    async def child_acl(self, aggregation_id: int, child_type: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/aggregations/{aggregation_id}/default-child-{child_type}-permissions")

    async def replace_child_acl(self, aggregation_id: int, child_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PUT", f"/api/v1/aggregations/{aggregation_id}/default-child-{child_type}-permissions", json=payload)

    async def preview_child_acl(self, aggregation_id: int, child_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/aggregations/{aggregation_id}/default-child-{child_type}-permissions/preview", json=payload)

    async def event_history_operations(self) -> list[str]:
        return await self.request("GET", "/api/v1/event-history/operations")

    async def audit_actors(self, query: str, *, entity_type=None, actor_type=None):
        params = {"q": query, "limit": 25}
        if entity_type:
            params["entity_type"] = entity_type
        if actor_type:
            params["actor_type"] = actor_type
        return await self.request("GET", "/api/v1/event-history/actors", params=params, _cancellable_read=True)

    async def event_history_filter_options(self) -> dict[str, list[str]]:
        return await self.request("GET", "/api/v1/event-history/filter-options")

    async def search_request(
        self, resource: str, payload: dict[str, Any], **params: Any,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/{resource}/search", json=payload,
            params={key: value for key, value in params.items() if value is not None},
        )

    async def active_people(
        self, query: str = "", *, limit: int = 25, offset: int = 0,
    ) -> dict[str, Any]:
        conditions: list[dict[str, Any]] = [
            {"field": "status", "operator": "eq", "value": "active"},
            {"field": "account_type", "operator": "eq", "value": "person"},
        ]
        term = query.strip()
        if term:
            conditions.append({"or": [
                {"field": "name", "operator": "contains_ci", "value": term},
                {"field": "email", "operator": "contains_ci", "value": term},
                {"field": "external_id", "operator": "contains_ci", "value": term},
            ]})
        return await self.search_request("users", {
            "where": {"and": conditions},
            "sort": [{"field": "name", "direction": "asc"}],
            "limit": limit,
            "offset": offset,
        })

    async def relationship_page(
        self, resource: str, search_fields: tuple[str, ...], query: str = "", *,
        limit: int = 25, offset: int = 0,
        filters: dict[str, Any] | None = None,
        eligible_classifications: bool = False,
    ) -> dict[str, Any]:
        # All record/aggregation relationship pickers also match description.
        # Preserve the caller's primary field for sorting and avoid duplicates.
        if resource in {"aggregations", "records"}:
            search_fields = tuple(dict.fromkeys((*search_fields, "description")))
        conditions: list[dict[str, Any]] = [
            {"field": field, "operator": "eq", "value": value}
            for field, value in (filters or {}).items()
            if value is not None
        ]
        term = query.strip()
        if term:
            conditions.append({"or": [
                {"field": field, "operator": "contains_ci", "value": term}
                for field in search_fields
            ]})
        payload: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "sort": [{"field": search_fields[0], "direction": "asc"}],
        }
        if conditions:
            payload["where"] = {"and": conditions}
        return await self.search_request(
            resource, payload,
            **({"eligible": True} if eligible_classifications else {}),
        )

    async def administration_reference_page(
        self, resource: str, *, query: str = "", sort: str = "name",
        limit: int = 25, offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if resource not in {"profiles", "security-levels"}:
            raise ValueError("unsupported administration reference page")
        return await self.request(
            "GET", f"/api/v1/{resource}/page",
            params={key: value for key, value in {
                "q": query or None, "sort": sort, "limit": limit, "offset": offset,
                **(filters or {}),
            }.items() if value is not None},
        )

    async def full_text_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/api/v1/full-text-search", json=payload)

    async def execute_saved_search(
        self, saved_search_id: int, payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/saved-searches/{saved_search_id}/execute", json=payload,
        )

    async def saved_searches(self, **filters: Any) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/saved-searches", params=filters)

    async def saved_search_administration(self, **filters: Any) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/saved-searches/administration", params=filters)

    async def saved_search_audience_options(
        self, audience_kind: str, *, query: str = "", ids: list[int] | None = None,
        limit: int = 25, offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"q": query, "limit": limit, "offset": offset}
        if ids:
            params["ids"] = ",".join(str(value) for value in ids)
        return await self.request(
            "GET", f"/api/v1/saved-searches/audience-options/{audience_kind}", params=params,
        )

    async def saved_search(self, saved_search_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/saved-searches/{saved_search_id}")

    async def create_saved_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/api/v1/saved-searches", json=payload)

    async def update_saved_search(
        self, saved_search_id: int, version: int, payload: dict[str, Any],
        reason: str | None = None,
    ) -> dict[str, Any]:
        headers = {"If-Match": str(version)}
        if reason:
            headers["X-Change-Reason"] = reason
        return await self.request(
            "PUT", f"/api/v1/saved-searches/{saved_search_id}", json=payload,
            headers=headers,
        )

    async def delete_saved_search(
        self, saved_search_id: int, version: int, reason: str,
    ) -> None:
        await self.request(
            "DELETE", f"/api/v1/saved-searches/{saved_search_id}",
            headers={"If-Match": str(version), "X-Change-Reason": reason},
        )

    async def count(self, resource: str) -> int:
        result = await self.search_request(resource, {"limit": 1, "offset": 0})
        return int(result["total"])

    async def effective_aggregation_closure(
        self, aggregation_id: int,
    ) -> dict[str, Any] | None:
        result = await self.request(
            "GET", f"/api/v1/aggregations/{aggregation_id}/effective-closure",
        )
        return result.get("closure")

    async def dashboard_summary(
        self, *, recent_limit: int | None = None, recent_since: datetime | None = None,
    ) -> dict[str, Any]:
        return await self.request(
            "GET", "/api/v1/dashboard/summary",
            params={**({"recent_limit":recent_limit} if recent_limit is not None else {}),
                    **({"recent_since":recent_since.isoformat()} if recent_since is not None else {})},
        )

    async def dashboard_reviews(
        self, state: str, *, limit: int = 25, offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self.request(
            "GET", "/api/v1/dashboard/reviews",
            # Fetch one look-ahead row so the UI can enable Next without a
            # separate count query or downloading every review.
            params={"state": state, "limit": limit + 1, "offset": offset},
        )

    async def search(
        self, resource: str, query: str, fields: tuple[str, ...],
        *, owning_org_unit_id: int | None = None,
    ) -> list[dict[str, Any]]:
        term = query.strip()
        if not term:
            return []
        conditions = [
            {"field": field, "operator": "contains_ci", "value": term}
            for field in fields
        ]
        where: dict[str, Any] = {"or": conditions}
        if owning_org_unit_id is not None and resource in {"aggregations", "records"}:
            where = {"and": [
                where,
                {
                    "field": "owning_org_unit_id", "operator": "eq",
                    "value": owning_org_unit_id,
                },
            ]}
        result = await self.request(
            "POST",
            f"/api/v1/{resource}/search",
            json={"where": where, "limit": 100, "offset": 0},
        )
        return result["items"]

    async def _recent_entities_from_events(
        self,
        resource: str,
        operation: str,
        actor_user_id: int | None,
        limit: int,
        since: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        entity_type = {
            "aggregations": "aggregation",
            "records": "record",
            "classifications": "classification",
        }[resource]
        conditions: list[dict[str, Any]] = [
            {"field": "entity_type", "operator": "eq", "value": entity_type},
            {"field": "operation", "operator": "eq", "value": operation},
        ]
        if actor_user_id is not None:
            conditions.append(
                {"field": "actor_user_id", "operator": "eq", "value": actor_user_id}
            )
        if since is not None:
            conditions.append({
                "field": "occurred_at",
                "operator": "gte",
                "value": since.isoformat() if isinstance(since, datetime) else since,
            })
        events = await self.search_request("event-history", {
            "where": {"and": conditions},
            "sort": [{"field": "occurred_at", "direction": "desc"}],
            "limit": 200,
        })
        entity_ids = []
        activity_times: dict[int, str] = {}
        for event in events["items"]:
            if event["entity_id"] not in entity_ids:
                entity_ids.append(event["entity_id"])
                activity_times[event["entity_id"]] = event["occurred_at"]
            if len(entity_ids) == limit:
                break
        results = await asyncio.gather(
            *(self.get(resource, entity_id) for entity_id in entity_ids),
            return_exceptions=True,
        )
        return [
            {**result, "_activity_at": activity_times[entity_id]}
            for entity_id, result in zip(entity_ids, results)
            if isinstance(result, dict)
        ]

    async def _recent_entities_from_my_activity(
        self,
        resource: str,
        operation: str,
        limit: int,
        since: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        entity_type = {"aggregations": "aggregation", "records": "record"}[resource]
        parsed_since = (
            since if isinstance(since, datetime)
            else datetime.fromisoformat(since.replace("Z", "+00:00")) if since
            else None
        )
        activity = await self.my_recent_activity(limit=limit, since=parsed_since)
        entries = [
            item for item in activity
            if item["entity_type"] == entity_type and item["operation"] == operation
        ][:limit]
        results = await asyncio.gather(
            *(self.get(resource, entry["entity_id"]) for entry in entries),
            return_exceptions=True,
        )
        return [
            {**result, "_activity_at": entry["occurred_at"]}
            for entry, result in zip(entries, results)
            if isinstance(result, dict)
        ]

    async def recent_resource_activity(
        self,
        resource: str,
        *,
        limit: int = 50,
        since: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        entity_type = {"aggregations": "aggregation", "records": "record"}[resource]
        parsed_since = (
            since if isinstance(since, datetime)
            else datetime.fromisoformat(since.replace("Z", "+00:00")) if since
            else None
        )
        activity = await self.my_recent_activity(limit=limit, since=parsed_since)
        entries = [item for item in activity if item["entity_type"] == entity_type]
        results = await asyncio.gather(
            *(self.get(resource, entry["entity_id"]) for entry in entries),
            return_exceptions=True,
        )
        return [
            {
                **result,
                "_activity_at": entry["occurred_at"],
                "_operation": entry["operation"],
            }
            for entry, result in zip(entries, results)
            if isinstance(result, dict)
        ]

    async def recently_created(
        self, resource: str, *, limit: int = 6, actor_user_id: int | None = None,
        since: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        if actor_user_id is not None:
            return await self._recent_entities_from_events(
                resource, "CREATE", actor_user_id, limit, since,
            )
        result = await self.search_request(resource, {
            "sort": [{"field": "date_created", "direction": "desc"}],
            "limit": limit,
        })
        return result["items"]

    async def recently_updated(
        self, resource: str, *, limit: int = 6, actor_user_id: int | None = None,
        since: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        if actor_user_id is not None:
            return await self._recent_entities_from_events(
                resource, "UPDATE", actor_user_id, limit, since,
            )
        if resource in {"aggregations", "records"}:
            return await self._recent_entities_from_my_activity(
                resource, "UPDATE", limit, since,
            )
        result = await self.search_request(resource, {
            "sort": [{"field": "date_updated", "direction": "desc"}],
            "limit": limit,
        })
        return result["items"]

    async def create(self, resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/{resource}", json=payload)

    async def update(
        self, resource: str, entity_id: int, version: int, payload: dict[str, Any],
        *, change_reason: str | None = None,
    ) -> dict[str, Any]:
        headers = {"If-Match": str(version)}
        if change_reason:
            headers["X-Change-Reason"] = change_reason
        return await self.request(
            "PATCH",
            f"/api/v1/{resource}/{entity_id}",
            json=payload,
            headers=headers,
        )

    async def delete(
        self, resource: str, entity_id: int, version: int, *, reason: str | None = None,
    ) -> None:
        headers = {"If-Match": str(version)}
        if reason:
            headers["X-Change-Reason"] = reason
        await self.request(
            "DELETE",
            f"/api/v1/{resource}/{entity_id}",
            headers=headers,
        )

    async def deletion_preflight(self, resource: str, entity_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/{resource}/{entity_id}/deletion-preflight")

    async def preview_security_level_change(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request(
            "POST", "/api/v1/security-level-changes/preview", json=payload,
        )

    async def apply_security_level_change(
        self, payload: dict[str, Any], *, reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST", "/api/v1/security-level-changes/apply", json=payload,
            headers={"X-Change-Reason": reason},
        )

    async def profile_privileges(self, profile_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/api/v1/profiles/{profile_id}/privileges")

    async def profile_impact(self, profile_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/profiles/{profile_id}/impact")

    async def replace_profile_privileges(
        self, profile_id: int, version: int, privilege_ids: list[int], *, reason: str,
    ) -> dict[str, Any]:
        return await self.request(
            "PUT", f"/api/v1/profiles/{profile_id}/privileges",
            json={"privilege_ids": privilege_ids},
            headers={"If-Match": str(version), "X-Change-Reason": reason},
        )

    async def set_active(
        self, resource: str, entity_id: int, version: int, *, active: bool,
    ) -> dict[str, Any]:
        action = "activate" if active else "deactivate"
        return await self.request(
            "POST", f"/api/v1/{resource}/{entity_id}/{action}",
            headers={"If-Match": str(version)},
        )

    async def set_user_suspended(
        self, user_id: int, version: int, *, suspended: bool,
    ) -> dict[str, Any]:
        action = "suspend" if suspended else "unsuspend"
        return await self.request(
            "POST", f"/api/v1/users/{user_id}/{action}",
            headers={"If-Match": str(version)},
        )

    async def upload_component(self, record_id: int, component_order: int, name: str, content: bytes, mime_type: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/api/v1/records/{record_id}/digital-components/upload",
            data={"component_order": str(component_order)},
            files={"file": (name, content, mime_type or "application/octet-stream")},
        )

    async def component_page(
        self, record_id: int, *, limit: int = 25, offset: int = 0,
    ) -> dict[str, Any]:
        """Return one authorized, deterministically ordered component page."""
        return await self.search_request("digital-components", {
            "where": {"field": "record_id", "operator": "eq", "value": record_id},
            "sort": [
                {"field": "component_order", "direction": "asc"},
                {"field": "id", "direction": "asc"},
            ],
            "limit": limit,
            "offset": offset,
        })

    async def component_count(self, record_id: int) -> int:
        return int((await self.component_page(record_id, limit=1))["total"])

    async def reorder_components(self, record_id: int, components: list[dict[str, int]]) -> None:
        await self.request("PUT", f"/api/v1/records/{record_id}/digital-components/order", json={"components": components})

    async def move_component(self, record_id: int, component_id: int, direction: int) -> None:
        await self.request(
            "POST",
            f"/api/v1/records/{record_id}/digital-components/{component_id}/move",
            json={"direction": direction},
        )

    async def delete_component(self, component_id: int, version: int) -> None:
        await self.request("DELETE", f"/api/v1/digital-components/{component_id}", headers={"If-Match": str(version)})

    async def download_component(self, component_id: int) -> bytes:
        return await self.request("GET", f"/api/v1/digital-components/{component_id}/content")

    async def view_component_pdf(self, component_id: int) -> bytes:
        return await self.request("GET", f"/api/v1/digital-components/{component_id}/rendition")

    async def print_component_pdf(self, component_id: int) -> bytes:
        return await self.request("GET", f"/api/v1/digital-components/{component_id}/print-rendition")

    async def reindex_component(self, component_id: int) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/digital-components/{component_id}/reindex")

    async def reindex_record(self, record_id: int) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/records/{record_id}/reindex")

    async def indexing_status(self, status_url: str) -> dict[str, Any]:
        return await self.request("GET", status_url)

    async def component_indexing_status(self, component_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/digital-components/{component_id}/indexing-status")

    async def create_record_draft(self) -> dict[str, Any]:
        return await self.request("POST", "/api/v1/record-drafts", json={})

    async def update_record_draft(self, draft_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", f"/api/v1/record-drafts/{draft_id}", json=payload)

    async def draft_components(self, draft_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/api/v1/record-drafts/{draft_id}/components")

    async def upload_draft_component(self, draft_id: int, component_order: int, name: str, content: bytes, mime_type: str) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/v1/record-drafts/{draft_id}/components",
            data={"component_order": str(component_order)},
            files={"file": (name, content, mime_type or "application/octet-stream")},
        )

    async def reorder_draft_components(self, draft_id: int, components: list[dict[str, int]]) -> None:
        await self.request("PUT", f"/api/v1/record-drafts/{draft_id}/components/order", json={"components": components})

    async def delete_draft_component(self, draft_id: int, component_id: int) -> None:
        await self.request("DELETE", f"/api/v1/record-drafts/{draft_id}/components/{component_id}")

    async def commit_record_draft(
        self, draft_id: int, creator_acl_role_id: int | None = None, *, capture: bool = False,
    ) -> dict[str, Any]:
        params = (
            {"creator_acl_role_id": creator_acl_role_id}
            if creator_acl_role_id is not None else None
        )
        return await self.request(
            "POST", f"/api/v1/record-drafts/{draft_id}/commit", params=params, timeout=660 if capture else 30,
        )

    async def discard_record_draft(self, draft_id: int) -> None:
        await self.request("DELETE", f"/api/v1/record-drafts/{draft_id}")

    async def recent_classifications(self, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return await self.request("GET", "/api/v1/classifications/recent", params={**({"limit":limit} if limit is not None else {}), "offset":offset})

    async def classification_path(self, classification_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/api/v1/classifications/{classification_id}/path")

    async def effective_retention_rule(self, aggregation_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/aggregations/{aggregation_id}/effective-retention-rule")

    async def aggregation_retention_rule(self, aggregation_id: int) -> dict[str, Any] | None:
        return await self.request("GET", f"/api/v1/aggregations/{aggregation_id}/retention-rule")

    async def put_aggregation_retention_rule(
        self, aggregation_id: int, payload: dict[str, Any], version: int | None = None,
    ) -> dict[str, Any]:
        return await self.request(
            "PUT", f"/api/v1/aggregations/{aggregation_id}/retention-rule",
            params={"version": version} if version else {}, json=payload,
            headers={"X-Change-Reason": payload["justification"]},
        )

    async def delete_aggregation_retention_rule(
        self, aggregation_id: int, version: int, reason: str,
    ) -> None:
        await self.request(
            "DELETE", f"/api/v1/aggregations/{aggregation_id}/retention-rule",
            headers={"If-Match": str(version), "X-Change-Reason": reason},
        )

    async def classification_effective_rule(self, classification_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/classifications/{classification_id}/effective-retention-rule")

    async def classification_retention_rule(self, classification_id: int) -> dict[str, Any] | None:
        return await self.request("GET", f"/api/v1/classifications/{classification_id}/retention-rule")

    async def put_classification_retention_rule(
        self, classification_id: int, payload: dict[str, Any], version: int | None = None,
    ) -> dict[str, Any]:
        return await self.request(
            "PUT", f"/api/v1/classifications/{classification_id}/retention-rule",
            params={"version": version} if version else {}, json=payload,
        )

    async def user_roles(self, user_id: int, **filters: Any) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/users/{user_id}/roles", params=filters)

    async def role_users(self, role_id: int, **filters: Any) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/roles/{role_id}/users", params=filters)

    async def delete_assignment(self, assignment_id: int, version: int) -> None:
        await self.request(
            "DELETE",
            f"/api/v1/user-role-assignments/{assignment_id}",
            headers={"If-Match": str(version)},
        )

    async def disposition_page(self, path: str, **parameters: Any) -> dict[str, Any]:
        """Live bounded pages; use the existing identity-scoped in-flight reads."""
        return await self.request('GET', '/api/v1/disposition/' + path,
                                  params={key: value for key, value in parameters.items() if value is not None})

    async def disposition_command(self, path: str, payload: dict[str, Any], *, reason: str,
                                  version: int | None = None) -> dict[str, Any]:
        headers = {'X-Change-Reason': reason}
        if version is not None:
            headers['If-Match'] = str(version)
        return await self.request('POST', '/api/v1/disposition/' + path, json=payload, headers=headers)


    async def correct_disposition_evidence(self, job_id, document_id, *, version, command_id,
                                           acting_role_id, destination_token, reason, name, content, mime_type):
        return await self.request('POST',f'/api/v1/disposition/jobs/{job_id}/documents/{document_id}/corrections',
          data={'command_id':str(command_id),'acting_role_id':str(acting_role_id),'destination_token':destination_token},
          files={'file':(name,content,mime_type)},headers={'If-Match':str(version),'X-Change-Reason':reason})

    async def revise_disposition_template(self, job_id, kind, *, command_id, acting_role_id,
                                          expected_reference, reason, name, content):
        return await self.request('POST',f'/api/v1/disposition/jobs/{job_id}/templates/{kind}/revisions',
          data={'command_id':str(command_id),'acting_role_id':str(acting_role_id),'expected_reference':expected_reference},
          files={'file':(name,content,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
          headers={'X-Change-Reason':reason})
