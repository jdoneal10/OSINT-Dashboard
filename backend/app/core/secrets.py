"""Secret lookup: macOS Keychain first (via ``keyring``), then environment / ``.env``.

Secret values are returned as :class:`pydantic.SecretStr` and are never logged.
Only secret *names* ever appear in log messages.

CLI::

    uv run python -m app.core.secrets set ANTHROPIC_API_KEY   # prompts, stores in Keychain
    uv run python -m app.core.secrets check ANTHROPIC_API_KEY # reports where it was found
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
from typing import Literal

import keyring
import keyring.errors
from dotenv import dotenv_values
from pydantic import SecretStr

from app.core.config import get_settings

KEYRING_SERVICE = "cartel-osint"

log = logging.getLogger(__name__)

SecretOrigin = Literal["keychain", "env", "dotenv"]


class MissingSecretError(RuntimeError):
    """Raised when a required secret is not present in any backend."""


def _from_keychain(name: str) -> str | None:
    try:
        value: str | None = keyring.get_password(KEYRING_SERVICE, name)
    except keyring.errors.KeyringError:
        log.warning("Keychain lookup failed for secret %s; falling back to environment", name)
        return None
    return value or None


def _from_dotenv(name: str) -> str | None:
    env_file = get_settings().repo_root / ".env"
    if not env_file.is_file():
        return None
    return dotenv_values(env_file).get(name) or None


def lookup_secret(name: str) -> tuple[SecretStr, SecretOrigin] | None:
    """Return the secret and where it came from, or ``None`` if absent everywhere."""
    if value := _from_keychain(name):
        return SecretStr(value), "keychain"
    if value := os.environ.get(name):
        return SecretStr(value), "env"
    if value := _from_dotenv(name):
        return SecretStr(value), "dotenv"
    return None


def get_secret(name: str) -> SecretStr | None:
    found = lookup_secret(name)
    return found[0] if found else None


def require_secret(name: str) -> SecretStr:
    secret = get_secret(name)
    if secret is None:
        raise MissingSecretError(
            f"Secret {name} not found in Keychain (service {KEYRING_SERVICE!r}), "
            "environment, or .env"
        )
    return secret


def _cli(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in {"set", "check"}:
        print("usage: python -m app.core.secrets {set|check} NAME", file=sys.stderr)
        return 2
    command, name = argv
    if command == "set":
        value = getpass.getpass(f"{name}: ")
        if not value:
            print("empty value; nothing stored", file=sys.stderr)
            return 1
        keyring.set_password(KEYRING_SERVICE, name, value)
        print(f"stored {name} in Keychain service {KEYRING_SERVICE!r}")
        return 0
    found = lookup_secret(name)
    print(f"{name}: found in {found[1]}" if found else f"{name}: not found")
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
