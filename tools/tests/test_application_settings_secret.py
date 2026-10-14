"""Encryption and deployment precedence without a database or real credentials."""
import os
import stat

from cryptography.fernet import Fernet
import pytest

from backend.services.api.application_settings_registry import SettingsInvalid
from backend.services.api.application_settings_secret import decrypt, encrypt, initialize_local_key
from backend.services.api.config import load_environment


def test_authenticated_ciphertext_is_random_and_bound_to_database(monkeypatch):
    monkeypatch.setenv("APPLICATION_SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    first = encrypt("fixture-password-سر", "database-one")
    second = encrypt("fixture-password-سر", "database-one")
    assert first != second and "fixture-password" not in first
    recovered = decrypt(first.encode(), "database-one")
    assert recovered.get_secret_value() == "fixture-password-سر"
    assert "fixture-password" not in repr(recovered)
    for value, database in ((first.encode(), "database-two"), (first[:-10].encode() + b"AAAAAAAAAA", "database-one"), (b"plaintext", "database-one")):
        with pytest.raises(SettingsInvalid, match="secret_unavailable"):
            decrypt(value, database)
    monkeypatch.setenv("APPLICATION_SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(SettingsInvalid, match="secret_unavailable"):
        decrypt(first.encode(), "database-one")


@pytest.mark.parametrize("key", [None, "", "invalid-key", "private-non-ascii-سر"])
def test_unavailable_key_fails_without_disclosing_input(monkeypatch, key):
    monkeypatch.delenv("APPLICATION_SETTINGS_ENCRYPTION_KEY", raising=False)
    if key is not None:
        monkeypatch.setenv("APPLICATION_SETTINGS_ENCRYPTION_KEY", key)
    with pytest.raises(SettingsInvalid) as failure:
        encrypt("fixture-private-password", "db")
    assert str(failure.value) == "application_settings_secret_unavailable"


def test_shell_key_overrides_dotenv_and_dotenv_loads_when_unset(tmp_path, monkeypatch):
    local, production = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    path = tmp_path / ".env"
    path.write_text(f"APPLICATION_SETTINGS_ENCRYPTION_KEY={local}\n")
    monkeypatch.setenv("APPLICATION_SETTINGS_ENCRYPTION_KEY", production)
    load_environment(path)
    token = encrypt("fixture-password", "db").removeprefix("fernet:v1:")
    assert b"fixture-password" in Fernet(production).decrypt(token.encode())
    monkeypatch.delenv("APPLICATION_SETTINGS_ENCRYPTION_KEY")
    load_environment(path)
    assert os.environ["APPLICATION_SETTINGS_ENCRYPTION_KEY"] == local


def test_local_initialization_preserves_existing_bytes_and_is_idempotent(tmp_path):
    path = tmp_path / ".env"
    previous = b"EXISTING_VALUE='private fixture'\n"
    path.write_bytes(previous)
    assert initialize_local_key(path)
    current = path.read_bytes()
    assert current.startswith(previous)
    assert not initialize_local_key(path)
    assert path.read_bytes() == current
    empty = tmp_path / "empty-setting.env"
    empty.write_bytes(b"export APPLICATION_SETTINGS_ENCRYPTION_KEY=\n")
    assert not initialize_local_key(empty)
    assert empty.read_bytes() == b"export APPLICATION_SETTINGS_ENCRYPTION_KEY=\n"
    new = tmp_path / "new.env"
    assert initialize_local_key(new)
    assert stat.S_IMODE(new.stat().st_mode) == 0o600
