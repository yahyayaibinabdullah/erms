import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_DIR / ".env", override=False)


def api_url() -> str:
    return os.getenv("WEBUI_API_URL", "http://127.0.0.1:8000").rstrip("/")


def host() -> str:
    return os.getenv("WEBUI_HOST", "0.0.0.0")


def port() -> int:
    return int(os.getenv("WEBUI_PORT", "8080"))


def reload_enabled() -> bool:
    return os.getenv("WEBUI_RELOAD", "false").strip().lower() in {"1", "true", "yes", "on"}


def full_text_search_enabled() -> bool:
    return os.getenv("WEBUI_FULL_TEXT_SEARCH_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def storage_secret() -> str:
    return os.getenv("WEBUI_STORAGE_SECRET", "local-development-change-me")


def database_display_name(language_tag: str) -> str:
    default_name = os.getenv("DATABASE_DISPLAY_NAME", "").strip()
    if not default_name:
        raise RuntimeError("DATABASE_DISPLAY_NAME is required")
    language = language_tag.strip().split("-", 1)[0].upper()
    localized_name = os.getenv(f"DATABASE_DISPLAY_NAME_{language}", "").strip()
    return localized_name or default_name


def default_root_aggregation_medium(configuration) -> str:
    return configuration["DEFAULT_ROOT_AGGREGATION_MEDIUM"]


def dashboard_recent_item_limit(configuration) -> int:
    return configuration["DASHBOARD_RECENT_ITEM_LIMIT"]


def dashboard_recent_days(configuration) -> int:
    return configuration["DASHBOARD_RECENT_DAYS"]


def dashboard_favourite_item_limit(configuration) -> int:
    return configuration["DASHBOARD_FAVOURITE_ITEM_LIMIT"]


def classification_recent_selection_limit(configuration) -> int:
    return configuration["CLASSIFICATION_RECENT_SELECTION_LIMIT"]


def user_details_session_limit(configuration) -> int:
    return configuration["USER_DETAILS_SESSION_LIMIT"]
