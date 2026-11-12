"""Raw snapshot storage: every pull is written to data/raw/<source>/<date>/ before parsing.

data/raw/ is gitignored and blocked by a pre-commit hook (CLAUDE.md hard rule 5).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass(frozen=True)
class RawSnapshot:
    path: Path
    sha256: str
    size: int


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_raw(
    source: str,
    run_id: int,
    name: str,
    content: bytes,
    *,
    today: dt.date | None = None,
) -> RawSnapshot:
    """Write ``content`` to ``data/raw/<source>/<YYYY-MM-DD>/<run_id>-<name>``."""
    day = (today or dt.datetime.now(dt.UTC).date()).isoformat()
    directory = get_settings().raw_dir / source / day
    directory.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    path = directory / f"{run_id}-{safe}"
    path.write_bytes(content)
    return RawSnapshot(path=path, sha256=sha256_bytes(content), size=len(content))
