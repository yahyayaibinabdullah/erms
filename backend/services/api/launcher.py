import os
import shutil

import uvicorn

from .config import PROJECT_DIR, boolean_environment, integer_environment, required_environment
from .office_pool import launcher_pool


def main() -> None:
    required_environment("DATABASE_URL")

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    workers = int(os.getenv("API_WORKERS", "1"))
    reload_enabled = boolean_environment("API_RELOAD")

    if port < 1 or port > 65535:
        raise RuntimeError("API_PORT must be between 1 and 65535")
    if workers < 1:
        raise RuntimeError("API_WORKERS must be at least 1")
    if reload_enabled and workers != 1:
        raise RuntimeError("API_RELOAD=true requires API_WORKERS=1")

    office_workers = integer_environment("LIBREOFFICE_WORKERS", 1, minimum=1)
    office_binary = os.getenv("LIBREOFFICE_BINARY") or shutil.which("soffice") or "libreoffice"
    with launcher_pool(office_workers, office_binary):
        uvicorn.run(
            "backend.services.api.main:app",
            app_dir=str(PROJECT_DIR),
            host=host,
            port=port,
            workers=workers,
            reload=reload_enabled,
        )


if __name__ == "__main__":
    main()
