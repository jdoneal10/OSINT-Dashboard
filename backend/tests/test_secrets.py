from __future__ import annotations

import logging
from pathlib import Path

import keyring.errors
import pytest

from app.core import secrets
from app.core.config import get_settings

NAME = "OSINT_TEST_SECRET"
VALUE = "s3cret-value-never-logged"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(NAME, raising=False)
    monkeypatch.setattr(get_settings(), "repo_root", tmp_path)  # no real .env


def _keychain(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(secrets.keyring, "get_password", lambda _svc, _name: value)


def test_keychain_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    _keychain(monkeypatch, VALUE)
    monkeypatch.setenv(NAME, "from-env")
    found = secrets.lookup_secret(NAME)
    assert found is not None
    assert found[1] == "keychain"
    assert found[0].get_secret_value() == VALUE


def test_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _keychain(monkeypatch, None)
    monkeypatch.setenv(NAME, VALUE)
    found = secrets.lookup_secret(NAME)
    assert found is not None
    assert found[1] == "env"


def test_dotenv_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _keychain(monkeypatch, None)
    (tmp_path / ".env").write_text(f"{NAME}={VALUE}\n")
    found = secrets.lookup_secret(NAME)
    assert found is not None
    assert found[1] == "dotenv"
    assert found[0].get_secret_value() == VALUE


def test_keyring_failure_falls_back_and_never_logs_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom(_svc: str, _name: str) -> str:
        raise keyring.errors.KeyringError("locked")

    monkeypatch.setattr(secrets.keyring, "get_password", _boom)
    monkeypatch.setenv(NAME, VALUE)
    with caplog.at_level(logging.DEBUG):
        secret = secrets.get_secret(NAME)
    assert secret is not None
    assert VALUE not in caplog.text
    assert VALUE not in repr(secret)
    assert NAME in caplog.text


def test_require_secret_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _keychain(monkeypatch, None)
    with pytest.raises(secrets.MissingSecretError):
        secrets.require_secret(NAME)
