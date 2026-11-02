from __future__ import annotations

from backend.services.processing_workspace import working_copy_fds

import os
import hashlib
import logging
import resource
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


logger = logging.getLogger(__name__)


# Tika's plain-text output does not preserve reliable PDF page boundaries, so
# use a conservative document-level density gate before paying the cost of
# rendering and OCRing every page. Documents below the gate still take the OCR
# path used for scanned and text-poor PDFs.
PDF_NATIVE_MIN_CHARACTERS = 200
PDF_NATIVE_MIN_CHARACTERS_PER_PAGE = 100


def _run(*args,**kwargs):
    return subprocess.run(*args,pass_fds=working_copy_fds(),**kwargs)


class ExtractionError(RuntimeError):
    def __init__(self, code: str, summary: str, retryable: bool = False):
        super().__init__(summary)
        self.code, self.summary, self.retryable = code, summary[:500], retryable


APP_JAR_SHA512 = "5ad62881281d70e7db029c97f1efb3ac351343f27dfe2361e6351b84bcd7878675c368b2946adc6ea6ba630f6e1b211f43a59a81a9a0a26a5d8b279aced341dc"


def app_jar(home: Path) -> Path:
    jars = list(home.glob("tika-app-4.0.0.jar"))
    if len(jars) != 1 or not (home / "lib").is_dir():
        raise RuntimeError("TEXT_INDEXER_TIKA_HOME must be the complete official Tika 4.0.0 app distribution")
    return jars[0]


def self_test(home: Path) -> None:
    jar = app_jar(home)
    digest=hashlib.sha512()
    with jar.open("rb") as stream:
        while block:=stream.read(1024*1024): digest.update(block)
    if digest.hexdigest()!=APP_JAR_SHA512:
        raise RuntimeError("Tika app jar checksum does not match the pinned official distribution")
    if shutil.which("java") is None:
        raise RuntimeError("Java 17 or newer is required")
    version = _run(["java", "-version"], capture_output=True, text=True, timeout=10)
    if version.returncode:
        raise RuntimeError("Java is not runnable")
    listing = _run(["jar", "tf", str(jar)], capture_output=True, text=True, timeout=20)
    combined = listing.stdout
    for library in (home / "lib").glob("*.jar"):
        if "tika-pipes-fork-parser" in library.name:
            combined += library.name
    if "tika-pipes-fork-parser" not in combined and "PipesForkParser" not in combined:
        raise RuntimeError("official distribution lacks tika-pipes-fork-parser")
    for command in ("tesseract","pdfinfo","pdftoppm"):
        if shutil.which(command) is None:
            raise RuntimeError(f"{command} is required")


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (120, 125))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    if sys.platform.startswith("linux") and hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


def _tika_failure(stderr: str) -> tuple[str, str, bool]:
    """Map Tika failures without blaming content for runtime failures."""
    detail = stderr.casefold()
    if "password" in detail or "encrypteddocumentexception" in detail:
        return "password_protected", "document requires a password", False
    infrastructure = (
        (
            (
                "failed to initialize parser", "server initialization failed",
                "serverinitializationexception",
            ),
            "Tika fork parser failed to initialize",
        ),
        (
            ("couldn't connect to server", "couldn't reconnect", "socketexception"),
            "Tika fork parser communication failed",
        ),
        (
            ("could not create the java virtual machine", "outofmemoryerror"),
            "Tika JVM failed to start",
        ),
        (
            ("noclassdeffounderror", "classnotfoundexception", "unable to access jarfile"),
            "Tika runtime dependency is unavailable",
        ),
        (
            ("operation not permitted", "permission denied"),
            "Tika process was denied an operating-system resource",
        ),
    )
    for markers, summary in infrastructure:
        if any(marker in detail for marker in markers):
            return "extractor_unavailable", summary, True
    corrupt_markers = (
        "corrupt", "malformed", "invalid document", "invalid file",
        "unexpected end of file", "unexpected end-of-file", "error parsing",
        "cannot parse", "can't parse",
    )
    if any(marker in detail for marker in corrupt_markers):
        return "corrupt", "extractor rejected malformed content", False
    # A non-zero process exit without affirmative content evidence is an
    # extractor failure. Treating the unknown as corrupt is misleading and
    # prevents safe automatic retry after an infrastructure incident.
    return "extractor_unavailable", "Tika extraction process failed", True


def extract(home: Path, source: Path, timeout: int) -> str:
    jar = app_jar(home)
    config = Path(__file__).with_name("tika-config.json")
    milliseconds = timeout * 1000
    command = [
        "java", "-Xmx768m", "-jar", str(jar), f"--config={config}", "--fork",
        f"--task-timeout={milliseconds}", f"--progress-timeout={min(milliseconds, 60_000)}",
        "--fork-jvm-args=-Xmx768m", "--maxEmbeddedDepth=0", "--text", str(source),
    ]
    # The Tika Pipes fork isolates parser work. Deployment-level egress denial is
    # additionally mandatory; this worker itself never supplies network inputs.
    try:
        result = _run(
            command, cwd=home, capture_output=True, text=True, timeout=timeout,
            preexec_fn=_limits if os.name == "posix" else None,
            env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "TMPDIR": str(source.parent)},
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError("timeout", "extractor exceeded wall-clock limit", True) from exc
    except OSError as exc:
        logger.warning("Tika process could not be started: %s", type(exc).__name__)
        raise ExtractionError(
            "extractor_unavailable", "Tika process could not be started", True,
        ) from exc
    if result.returncode:
        code, summary, retryable = _tika_failure(result.stderr or "")
        logger.warning(
            "Tika extraction failed: exit_code=%s classification=%s",
            result.returncode, code,
        )
        raise ExtractionError(code, summary, retryable)
    return result.stdout


def extract_image_ocr(source: Path, timeout: int) -> str:
    if shutil.which("tesseract") is None:
        raise ExtractionError("extractor_unavailable", "Tesseract is not runnable", True)
    try:
        result = _run(
            ["tesseract", str(source), "stdout", "-l", "eng+ara", "--psm", "6"],
            capture_output=True,text=True,timeout=timeout,
            preexec_fn=_limits if os.name=="posix" else None,
            env={"PATH":os.environ.get("PATH",""),"LANG":"C.UTF-8","TMPDIR":str(source.parent)},
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError("timeout","OCR exceeded wall-clock limit",True) from exc
    if result.returncode:
        raise ExtractionError("corrupt","OCR rejected image content")
    return result.stdout


def pdf_page_count(source: Path, timeout: int = 20) -> int:
    try:
        result=_run(
            ["pdfinfo",str(source)],capture_output=True,text=True,timeout=timeout,
            preexec_fn=_limits if os.name=="posix" else None,
            env={"PATH":os.environ.get("PATH",""),"LANG":"C.UTF-8","TMPDIR":str(source.parent)},
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError("timeout","PDF inspection exceeded wall-clock limit",True) from exc
    if result.returncode:
        raise ExtractionError("corrupt","PDF metadata inspection failed")
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":",1)[1].strip())
    raise ExtractionError("corrupt","PDF page count is unavailable")


def pdf_native_text_is_sufficient(text: str, pages: int) -> bool:
    meaningful_characters = sum(character.isalnum() for character in text)
    required_characters = max(
        PDF_NATIVE_MIN_CHARACTERS,
        pages * PDF_NATIVE_MIN_CHARACTERS_PER_PAGE,
    )
    return meaningful_characters >= required_characters


def extract_pdf(home: Path,source: Path,timeout: int,max_pages: int,max_temp_bytes: int) -> tuple[str,bool]:
    pages=pdf_page_count(source,min(timeout,20))
    if pages>max_pages:
        raise ExtractionError("limit_exceeded","PDF exceeds configured page limit")
    native=extract(home,source,timeout)
    if pdf_native_text_is_sufficient(native, pages):
        return native,False
    with tempfile.TemporaryDirectory(prefix="pdf-ocr-",dir=source.parent) as directory:
        prefix=Path(directory)/"page"
        try:
            rendered=_run(
                ["pdftoppm","-png","-r","200","-f","1","-l",str(pages),str(source),str(prefix)],
                capture_output=True,text=True,timeout=timeout,
                preexec_fn=_limits if os.name=="posix" else None,
                env={"PATH":os.environ.get("PATH",""),"LANG":"C.UTF-8","TMPDIR":directory},
            )
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError("timeout","PDF OCR rendering exceeded wall-clock limit",True) from exc
        if rendered.returncode:
            if rendered.returncode < 0:
                raise ExtractionError("timeout","PDF OCR rendering exceeded resource limit",True)
            raise ExtractionError("corrupt","PDF OCR rendering failed")
        images=sorted(Path(directory).glob("page-*.png"))
        if len(images)!=pages or sum(image.stat().st_size for image in images)>max_temp_bytes:
            raise ExtractionError("limit_exceeded","PDF OCR temporary output exceeds configured limit")
        ocr="\n\n".join(extract_image_ocr(image,timeout) for image in images)
    native_arabic=sum('\u0600'<=character<='\u06ff' for character in native)
    ocr_arabic=sum('\u0600'<=character<='\u06ff' for character in ocr)
    # The Tika 4.0.0 fork currently loses its configured Arabic OCR language.
    # Prefer explicit bilingual OCR only when it recovers materially more Arabic;
    # otherwise retain the higher-fidelity native text extraction.
    return (ocr,True) if ocr_arabic>max(20,native_arabic*2) else (native,False)
