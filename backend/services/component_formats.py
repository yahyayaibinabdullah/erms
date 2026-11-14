"""File formats supported by the saved and staged component viewers."""

CONVERTIBLE_EXTENSIONS = {
    ".doc", ".docx", ".odt", ".rtf",
    ".xls", ".xlsx", ".ods", ".csv",
    ".ppt", ".pptx", ".odp",
    ".md", ".msg", ".eml", ".html", ".txt", ".xml",
}
NATIVE_IMAGE_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/avif",
}


def native_preview_kind(mime_type: str | None) -> str | None:
    value = (mime_type or "").lower()
    if value in NATIVE_IMAGE_MIME_TYPES:
        return "image"
    if value.startswith("audio/"):
        return "audio"
    if value.startswith("video/"):
        return "video"
    return None
