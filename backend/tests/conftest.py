"""Test setup: every test talks to the ``osint_test`` database, migrated to head once."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_DB_URL = os.environ.get(
    "OSINT_TEST_DATABASE_URL",
    "postgresql+psycopg://osint:osint@127.0.0.1:5432/osint_test",
)
# Point the app at the test database before any app module reads settings.
os.environ["OSINT_DATABASE_URL"] = TEST_DB_URL
os.environ["OSINT_ENV"] = "test"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.reference.load import load_reference  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

get_settings.cache_clear()
get_engine.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app/db/migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def raw_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Raw snapshots written during tests go to a temp dir, never data/raw/."""
    raw = tmp_path / "raw"
    monkeypatch.setattr(get_settings(), "data_raw_dir", raw)
    return raw


@pytest.fixture
def seeded(session: Session) -> Session:
    """Load the real committed reference data (sources, nodes, AOI, actors)."""
    load_reference(session, get_settings().reference_dir)
    session.commit()
    return session


@pytest.fixture
def session() -> Iterator[Session]:
    with session_factory()() as s:
        yield s


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ref_fixture_dir() -> Path:
    return FIXTURES / "reference"
