"""Outbound allowlist (ADR 0008 §2; CLAUDE.md "Do not").

The backend may send requests only to a domain in ``data/reference/outbound.yaml`` (subdomains
included), to the host of an active feed in ``feeds.yaml``, or to loopback (the local
Ollama model). ``check`` raises ``OutboundBlockedError`` for anything else.
``PoliteClient`` checks every request and every redirect hop; the local filter and the Claude
API client check their fixed endpoints.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.ingest.feeds import active


class OutboundBlockedError(RuntimeError):
    """The request's host is not on the outbound allowlist."""


class Destination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    purpose: str
    basis: str


class OutboundFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    destinations: list[Destination]


def allowlist_path() -> Path:
    return get_settings().reference_dir / "outbound.yaml"


@lru_cache
def _load(path: Path, mtime: float) -> OutboundFile:  # mtime busts the cache on edits
    return OutboundFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _feed_hosts() -> set[str]:
    hosts: set[str] = set()
    for feed in active():
        hosts.add(feed.domain.lower())
        if feed.url:
            hosts.add((urlsplit(str(feed.url)).hostname or "").lower())
    return {_bare(h) for h in hosts if h}


def _bare(host: str) -> str:
    return host.removeprefix("www.")


def allowed_domains(path: Path | None = None) -> frozenset[str]:
    path = path or allowlist_path()
    listed = {d.domain.lower() for d in _load(path, path.stat().st_mtime).destinations}
    return frozenset({_bare(d) for d in listed} | _feed_hosts())


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_allowed(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    if _is_loopback(host):
        return True
    return any(host == d or host.endswith("." + d) for d in allowed_domains())


def check(url: str) -> None:
    if not is_allowed(url):
        host = urlsplit(url).hostname or url
        raise OutboundBlockedError(
            f"{host} is not on the outbound allowlist (data/reference/outbound.yaml or a "
            "feed in feeds.yaml); see ADR 0008 §2"
        )
