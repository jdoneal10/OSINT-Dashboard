from __future__ import annotations

import ssl

from app.ingest import http, tls


def test_context_verifies_and_adds_the_bundled_intermediates() -> None:
    ctx = tls.context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname
    subjects = {dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()}
    assert "DigiCert Global G2 TLS RSA SHA256 2020 CA1" in subjects
    assert "DigiCert Global Root G2" in subjects  # certifi's roots are still there


def test_polite_client_uses_the_context() -> None:
    with http.PoliteClient() as client:
        pool = client._client._transport._pool  # type: ignore[attr-defined]
        assert pool._ssl_context is tls.context()
