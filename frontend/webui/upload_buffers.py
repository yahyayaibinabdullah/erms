"""Preserve temporary upload bytes before asynchronous processing."""
from nicegui import events

def buffer_upload_batch(event: events.MultiUploadEventArguments) -> list[tuple[bytes, str, str]]:
    """Copy NiceGUI temporary uploads before any awaited API operation can release them."""
    return [
        (content_source.read(), name, mime_type or "application/octet-stream")
        for content_source, name, mime_type in zip(event.contents, event.names, event.types)
    ]
