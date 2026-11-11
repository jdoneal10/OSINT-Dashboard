from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Actor, ActorAlias
from app.reference.load import (
    ReferenceDataError,
    load_reference,
    parse_reference_dir,
    table_counts,
)


def _load(session: Session, ref_dir: Path) -> dict[str, int]:
    load_reference(session, ref_dir)
    session.commit()
    return table_counts(session)


def test_load_is_idempotent(session: Session, ref_fixture_dir: Path) -> None:
    first = _load(session, ref_fixture_dir)
    second = _load(session, ref_fixture_dir)
    assert first == second
    assert first == {"reference_areas": 2, "nodes": 3, "actors": 2, "actor_aliases": 4}


def test_parent_and_canonical_alias(session: Session, ref_fixture_dir: Path) -> None:
    _load(session, ref_fixture_dir)
    faction = session.scalars(select(Actor).where(Actor.slug == "test-faction")).one()
    parent = session.scalars(select(Actor).where(Actor.slug == "test-cartel")).one()
    assert faction.parent_id == parent.id
    aliases = set(
        session.scalars(select(ActorAlias.alias_normalized).where(ActorAlias.actor_id == parent.id))
    )
    assert aliases == {"cartel de prueba", "cdp", "test cartel"}


def test_removed_alias_is_pruned(session: Session, ref_fixture_dir: Path, tmp_path: Path) -> None:
    ref = tmp_path / "ref"
    shutil.copytree(ref_fixture_dir, ref)
    _load(session, ref)
    yaml_path = ref / "actor_aliases.yaml"
    yaml_path.write_text(yaml_path.read_text().replace("      - CDP\n", ""))
    counts = _load(session, ref)
    assert counts["actor_aliases"] == 3


def _break(ref: Path, filename: str, old: str, new: str) -> None:
    path = ref / filename
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


@pytest.mark.parametrize(
    ("filename", "old", "new", "message"),
    [
        (
            "actor_aliases.yaml",
            "    sources:\n      - {title: Synthetic test fixture",
            "    sources: []\n    _dropped:\n      - {title: Synthetic test fixture",
            "citation",
        ),
        ("nodes.geojson", '"node_type": "poe"', '"node_type": "patrol_unit"', "node_type"),
        ("actor_aliases.yaml", "parent: test-cartel", "parent: nobody", "unknown parent"),
        ("aoi_test.geojson", '"phase": 1', '"phase": 9', "phase"),
    ],
)
def test_invalid_reference_data_is_rejected(
    ref_fixture_dir: Path, tmp_path: Path, filename: str, old: str, new: str, message: str
) -> None:
    ref = tmp_path / "ref"
    shutil.copytree(ref_fixture_dir, ref)
    _break(ref, filename, old, new)
    with pytest.raises(ReferenceDataError, match=message):
        parse_reference_dir(ref)


def test_missing_sources_key_is_rejected(ref_fixture_dir: Path, tmp_path: Path) -> None:
    ref = tmp_path / "ref"
    shutil.copytree(ref_fixture_dir, ref)
    data = json.loads((ref / "nodes.geojson").read_text())
    del data["features"][0]["properties"]["sources"]
    (ref / "nodes.geojson").write_text(json.dumps(data))
    with pytest.raises(ReferenceDataError, match="sources"):
        parse_reference_dir(ref)


def test_repository_reference_files_validate() -> None:
    """The committed data/reference files must always pass validation."""
    parsed, skipped = parse_reference_dir(get_settings().reference_dir)
    assert skipped == []
    assert parsed.nodes is not None
    assert parsed.actors is not None


def test_aoi_and_nodes_endpoints(
    client: TestClient, session: Session, ref_fixture_dir: Path
) -> None:
    _load(session, ref_fixture_dir)

    aoi = client.get("/reference/aoi", params={"phase": 1}).json()
    assert aoi["type"] == "FeatureCollection"
    assert {f["id"] for f in aoi["features"]} == {"mx-test-a", "us-test-b"}
    assert all(f["geometry"]["type"] == "MultiPolygon" for f in aoi["features"])
    assert all(f["properties"]["sources"] for f in aoi["features"])

    nodes = client.get("/reference/nodes").json()
    by_id = {f["id"]: f for f in nodes["features"]}
    assert by_id["poe-test"]["geometry"] == {"type": "Point", "coordinates": [-109.5, 31]}
    sector = by_id["sector-test"]
    assert sector["geometry"]["type"] == "MultiPolygon"
    lon, lat = sector["properties"]["label_point"]
    assert -110 < lon < -109
    assert 31 < lat < 32

    no_geom = by_id["sector-nogeom"]
    assert no_geom["geometry"] is None
    assert no_geom["properties"]["label_point"] is None

    only_poe = client.get("/reference/nodes", params={"node_type": "poe"}).json()
    assert [f["id"] for f in only_poe["features"]] == ["poe-test"]
