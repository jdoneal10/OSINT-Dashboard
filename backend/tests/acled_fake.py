"""Fake ACLED API (token, read, deleted) serving the synthetic fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.ingest import acled
from app.ingest.http import PoliteClient

FIX = Path(__file__).parent / "fixtures" / "acled"
TOKEN = "synthetic-test-token"  # not a real credential


def _json(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIX / f"{name}.json").read_text())
    return data


def fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = {"ACLED_USERNAME": "user@example.org", "ACLED_PASSWORD": "not-a-real-password"}
    monkeypatch.setattr(acled, "require_secret", lambda name: SecretStr(secrets[name]))


class FakeAcled:
    """Minimal fake of ACLED's token, read and deleted endpoints."""

    def __init__(self, events: dict[str, Any] | None = None, expire_once: bool = False) -> None:
        self.events = events  # if set, every read returns this page
        self.expire_once = expire_once
        self.calls: list[httpx.Request] = []
        self.token_requests = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        path = req.url.path
        if path == "/robots.txt":
            raise AssertionError("API calls must not consult robots.txt")
        if path == "/oauth/token":
            self.token_requests += 1
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            assert form["grant_type"] == "password"
            assert form["client_id"] == "acled"
            return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 86400})
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401)
        if self.expire_once:
            self.expire_once = False
            return httpx.Response(401)
        if path == "/api/acled/read":
            if self.events is not None:
                return httpx.Response(200, json=self.events)
            page = "events-page2" if req.url.params.get("cursor") == "c2" else "events-page1"
            return httpx.Response(200, json=_json(page))
        if path == "/api/deleted/read":
            return httpx.Response(200, json=_json("deleted"))
        return httpx.Response(404)

    def client(self) -> PoliteClient:
        return PoliteClient(
            transport=httpx.MockTransport(self.handler), min_interval=0, sleep=lambda _s: None
        )
