"""Preserve temporary upload bytes before asynchronous processing."""
from nicegui import events
import os
from tempfile import SpooledTemporaryFile


def retain_upload_file(source):
    """Own an upload after NiceGUI closes it, without copying large disk files."""
    try:
        descriptor = source.fileno()
    except (AttributeError, OSError):
        # Memory-only sources (including tests) have no duplicable descriptor.
        retained = SpooledTemporaryFile(max_size=1024 * 1024)
        try:
            source.seek(0)
            size = 0
            while chunk := source.read(1024 * 1024):
                retained.write(chunk)
                size += len(chunk)
            retained.seek(0)
            return retained, size
        except BaseException:
            retained.close()
            raise
    retained = os.fdopen(os.dup(descriptor), "rb")
    try:
        retained.seek(0)
        return retained, os.fstat(retained.fileno()).st_size
    except BaseException:
        retained.close()
        raise

def buffer_upload_batch(event: events.MultiUploadEventArguments) -> list[tuple[bytes, str, str]]:
    """Copy NiceGUI temporary uploads before any awaited API operation can release them."""
    return [
        (content_source.read(), name, mime_type or "application/octet-stream")
        for content_source, name, mime_type in zip(event.contents, event.names, event.types)
    ]
