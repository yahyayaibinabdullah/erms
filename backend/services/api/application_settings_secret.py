"""Server-only authenticated encryption; the key never enters the database.

The approved deployment key uses normal override=False dotenv loading. Missing
configuration does not block startup; only credential replacement/resolution.
"""
import argparse
import json
import os
from pathlib import Path
import re

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from .config import ENV_FILE  # Loads .env without overriding the shell environment.
from .application_settings_registry import SettingsInvalid


def _cipher():
    key = os.getenv("APPLICATION_SETTINGS_ENCRYPTION_KEY")
    try:
        if not key:
            raise ValueError
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise SettingsInvalid("application_settings_secret_unavailable") from None


def encrypt(value: str, database_id: str) -> str:
    try:
        payload = json.dumps({"database_id": database_id, "key": "SMTP_PASSWORD", "value": value}, ensure_ascii=False).encode("utf-8")
        return "fernet:v1:" + _cipher().encrypt(payload).decode("ascii")
    except UnicodeError:
        raise SettingsInvalid("application_settings_secret_unavailable") from None


def decrypt(value: bytes, database_id: str):
    cipher = _cipher()
    try:
        prefix = b"fernet:v1:"
        if not value.startswith(prefix):
            raise ValueError
        payload = json.loads(cipher.decrypt(value[len(prefix):]))
        if payload["database_id"] != database_id or payload["key"] != "SMTP_PASSWORD" or not isinstance(payload["value"], str):
            raise ValueError
        return SecretStr(payload["value"])
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError):
        raise SettingsInvalid("application_settings_secret_unavailable") from None


def initialize_local_key(path: Path) -> bool:
    """Append only a missing local deployment key, without displaying its value."""
    original = path.read_bytes() if path.exists() else b""
    if re.search(rb"(?m)^\s*(?:export\s+)?APPLICATION_SETTINGS_ENCRYPTION_KEY\s*=", original):
        return False
    line = b"\n# API settings encryption key; shell environment takes precedence.\nAPPLICATION_SETTINGS_ENCRYPTION_KEY=" + Fernet.generate_key() + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "ab") as stream:
        stream.write(line)
    return True


def main():
    parser = argparse.ArgumentParser(description="Append a missing local settings encryption key without changing existing private values.")
    parser.add_argument("--init-local-key", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    args = parser.parse_args()
    print("Added APPLICATION_SETTINGS_ENCRYPTION_KEY." if initialize_local_key(args.env_file) else "APPLICATION_SETTINGS_ENCRYPTION_KEY already defined; private value preserved.")


if __name__ == "__main__":
    main()
