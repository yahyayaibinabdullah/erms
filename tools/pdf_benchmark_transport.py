"""Disposable original-PDF benchmark instrumentation. Never installed in production."""

import asyncio
from pathlib import Path
import time

from tools.webui_test_events import EventWriter


class MeasuredPreviewTransport:
    """Meter document payloads on both NiceGUI WebSocket and same-origin HTTP."""

    def __init__(self, app, directory):
        self.app = app
        self.limited = Path(directory) / "limited-profile"
        self.events = EventWriter(Path(directory) / "pdf-transfer.jsonl")

    async def __call__(self, scope, receive, send):
        pdf = scope["type"] == "http" and scope["path"].startswith("/preview-pdf/")
        if not pdf and scope["type"] != "websocket":
            return await self.app(scope, receive, send)
        first = True

        async def observed(message):
            nonlocal first
            payload = message.get("body" if pdf else "bytes") or message.get("text") or b""
            if pdf or (
                len(payload) > 65536
                and (
                    "ermsPdfViewer.open" in payload
                    if isinstance(payload, str)
                    else b"ermsPdfViewer.open" in payload
                )
            ):
                size = len(payload.encode() if isinstance(payload, str) else payload)
                if self.limited.exists():
                    rate_mib = int(self.limited.read_text() or "32")
                    await asyncio.sleep((0.04 if first else 0) + size / (rate_mib * 1024 * 1024))
                first = False
                await send(message)
                if size:
                    self.events.append(
                        {"at": time.monotonic(), "bytes": size, "transport": "http" if pdf else "websocket"}
                    )
            else:
                await send(message)

        return await self.app(scope, receive, observed)


def observe_storage(directory):
    """Count logical bytes crossing the storage-provider boundary, including cancelled GETs."""
    from backend.services.api.content_storage import PostgreSQLContentStorage

    events = EventWriter(Path(directory) / "pdf-storage.jsonl")
    from backend.services.api import document_conversion
    try:
        from backend.services.api import converted_previews
    except ImportError:
        converted_previews = None  # Historical baseline has no rendition chunk reader.
    if converted_previews is not None:
        ranges = EventWriter(Path(directory) / "pdf-rendition-reads.jsonl")
        read_range = converted_previews.read_range

        def measured_range(*args):
            for chunk in read_range(*args):
                ranges.append({"at": time.monotonic(), "bytes": len(chunk)})
                yield chunk

        converted_previews.read_range = measured_range
    conversions = EventWriter(Path(directory) / "pdf-conversions.jsonl")
    run = document_conversion._run

    def timed_run(command, **kwargs):
        started = time.monotonic()
        try:
            return run(command, **kwargs)
        finally:
            if "--convert-to" in command:
                conversions.append({"at": started, "ms": round((time.monotonic() - started) * 1000)})

    document_conversion._run = timed_run
    old_read = PostgreSQLContentStorage.read

    def read(self, *args, **kwargs):
        payload = old_read(self, *args, **kwargs)
        if payload:
            events.append({"at": time.monotonic(), "bytes": len(payload)})
        return payload

    PostgreSQLContentStorage.read = read
    if hasattr(PostgreSQLContentStorage, "pdf_chunks"):
        original = PostgreSQLContentStorage.pdf_chunks

        def pdf_chunks(self, *args, **kwargs):
            chunks = original(self, *args, **kwargs)

            def measured():
                for chunk in chunks:
                    events.append({"at": time.monotonic(), "bytes": len(chunk)})
                    yield chunk

            return measured()

        PostgreSQLContentStorage.pdf_chunks = pdf_chunks
