import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_DIR / ".env"


def load_environment(env_file: Path = ENV_FILE) -> None:
    """Load local defaults without replacing real environment variables."""
    load_dotenv(dotenv_path=env_file, override=False)


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def default_working_timezone(connection) -> str:
    """Database-owned fallback for people without a saved timezone preference."""
    from .application_settings import cache
    return cache.for_connection(connection)["DEFAULT_WORKING_TIMEZONE"]


def boolean_environment(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def integer_environment(name: str, default: int, *, minimum: int = 0) -> int:
    raw_value = os.getenv(name)
    try:
        value = default if raw_value is None else int(raw_value)
    except ValueError as exception:
        raise RuntimeError(f"{name} must be an integer") from exception
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def float_environment(name: str, default: float, *, minimum: float = 0) -> float:
    raw_value = os.getenv(name)
    try:
        value = default if raw_value is None else float(raw_value)
    except ValueError as exception:
        raise RuntimeError(f"{name} must be a number") from exception
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def choice_environment(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise RuntimeError(f"{name} must be one of: {allowed}")
    return value


load_environment()
