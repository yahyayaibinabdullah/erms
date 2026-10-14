from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path



class ConversionUnavailable(RuntimeError):
    pass


class UnsupportedPreview(RuntimeError):
    pass


CONVERTIBLE_EXTENSIONS = {
    ".doc", ".docx", ".odt", ".rtf",
    ".xls", ".xlsx", ".ods", ".csv",
    ".ppt", ".pptx", ".odp",
    ".md", ".msg", ".eml", ".html", ".txt", ".xml",
}


def _libreoffice_binary() -> str:
    configured = os.getenv("LIBREOFFICE_BINARY", "").strip()
    binary = configured or shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        raise ConversionUnavailable(
            "LibreOffice is not available on the API server; download the original or install LibreOffice to enable this preview"
        )
    return binary


def pdf_rendition(content: bytes, file_name: str, mime_type: str, *, settings) -> tuple[bytes, str]:
    """Return PDF bytes and the rendering method used."""
    if mime_type.lower() == "application/pdf" or content.startswith(b"%PDF-"):
        return content, "original"

    suffix = Path(file_name).suffix.lower()
    if suffix not in CONVERTIBLE_EXTENSIONS:
        raise UnsupportedPreview(f"in-app preview is not supported for {suffix or mime_type}")

    timeout = settings["DOCUMENT_CONVERSION_TIMEOUT_SECONDS"]
    maximum = settings["MAX_RENDITION_SIZE_BYTES"]
    with tempfile.TemporaryDirectory(prefix="erms-rendition-") as temporary:
        workspace = Path(temporary)
        source = workspace / f"source{suffix}"
        output = workspace / "output"
        profile = workspace / "profile"
        output.mkdir()
        profile.mkdir()
        source.write_bytes(content)
        conversion_source = source
        method = "libreoffice"
        intermediary = None
        if suffix in {".msg", ".eml"}:
            intermediary = "email_to_html.py"
            method = (
                "extract-msg+libreoffice"
                if suffix == ".msg"
                else "stdlib-email+libreoffice"
            )
        elif suffix == ".xml":
            intermediary = "xml_to_html.py"
            method = "escaped-xml+libreoffice"
        elif suffix == ".xlsx":
            intermediary = "xlsx_to_preview.py"
            prepared = workspace / "prepared"
            prepared.mkdir()
            conversion_source = prepared / "source.xlsx"
            method = "xlsx-fit-to-page+libreoffice"
        if intermediary:
            if suffix != ".xlsx":
                conversion_source = workspace / "source.html"
            try:
                extraction = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).with_name(intermediary)),
                        str(source),
                        str(conversion_source),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=timeout,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
            except subprocess.TimeoutExpired as error:
                raise ConversionUnavailable("preview preparation timed out") from error
            if extraction.returncode != 0 or not conversion_source.is_file():
                detail = extraction.stderr.decode("utf-8", errors="replace").strip()
                raise ConversionUnavailable(
                    f"preview preparation failed{': ' + detail if detail else ''}"
                )
            if conversion_source.stat().st_size > maximum:
                raise ConversionUnavailable(
                    "prepared preview exceeds the configured rendition size limit"
                )
        command = [
            _libreoffice_binary(),
            "--headless", "--nologo", "--nodefault", "--nolockcheck", "--norestore",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to", "pdf", "--outdir", str(output), str(conversion_source),
        ]
        try:
            completed = subprocess.run(
                command, check=False, capture_output=True, timeout=timeout,
                env={**os.environ, "SAL_DISABLE_OPENCL": "1"},
            )
        except subprocess.TimeoutExpired as error:
            raise ConversionUnavailable("document conversion timed out") from error
        rendition = output / "source.pdf"
        if completed.returncode != 0 or not rendition.is_file():
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise ConversionUnavailable(f"LibreOffice could not convert this document{': ' + detail if detail else ''}")
        if rendition.stat().st_size > maximum:
            raise ConversionUnavailable("generated PDF exceeds the configured rendition size limit")
        return rendition.read_bytes(), method
