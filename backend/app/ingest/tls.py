"""TLS verification for every ingester.

certifi's roots plus the public CA intermediates in ``data/reference/tls/intermediates.pem``.
Some source servers send only their leaf certificate; browsers fetch the missing intermediate
themselves, Python does not. The bundled intermediates only help build the chain: it must still
end at a certifi root, and verification is never turned off.
"""

from __future__ import annotations

import ssl
from functools import cache

import certifi

from app.core.config import get_settings


@cache
def context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    bundle = get_settings().reference_dir / "tls" / "intermediates.pem"
    if bundle.exists():
        ctx.load_verify_locations(cafile=str(bundle))
    return ctx
