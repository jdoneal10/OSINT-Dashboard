"""Verify the stored Anthropic API key without printing it or spending tokens.

    uv run python -m app.enrich.llm.check

Calls the Models API (no token cost) through the gateway's pinned endpoint and reports only
"ok" or the error class and HTTP status. The key never appears in output or logs.
"""

from __future__ import annotations

import sys

import anthropic

from app.core.secrets import MissingSecretError
from app.enrich.llm.client import API_BASE_URL, Gateway


def main() -> int:
    try:
        models = Gateway().client.models.list(limit=1)
        first = next(iter(models.data), None)
    except MissingSecretError:
        print("ANTHROPIC_API_KEY is not stored (Keychain, environment or .env).")
        return 2
    except anthropic.AuthenticationError as exc:
        print(f"Key rejected by {API_BASE_URL}: HTTP {exc.status_code} (invalid or revoked key).")
        return 1
    except anthropic.APIError as exc:
        print(f"API error: {type(exc).__name__}")
        return 1
    print(
        f"API key OK ({API_BASE_URL}; models API reachable{', e.g. ' + first.id if first else ''})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
