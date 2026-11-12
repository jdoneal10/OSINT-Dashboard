from __future__ import annotations

from app.ingest.__main__ import main


def test_unknown_source_exits_nonzero() -> None:
    assert main(["no-such-source"]) == 2
