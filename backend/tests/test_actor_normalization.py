from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Actor
from app.enrich.actors import ActorIndex, actor_type_for, clean_name, split_actors


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Military Forces of Mexico (2018-)", "Military Forces of Mexico"),
        ("Police Forces of Mexico (2018-) State Police", "Police Forces of Mexico State Police"),
        ("Civilians (Mexico)", "Civilians"),
        ("  Sinaloa   Cartel ", "Sinaloa Cartel"),
    ],
)
def test_clean_name(raw: str, expected: str) -> None:
    assert clean_name(raw) == expected


@pytest.mark.parametrize(
    ("inter", "expected"),
    [
        ("State forces", "state"),
        ("1", "state"),
        ("Political militia", "armed_group"),
        ("4", "armed_group"),
        ("Civilians", "civilian"),
        ("Protesters", "other"),
        (None, "other"),
    ],
)
def test_actor_type_for(inter: str | None, expected: str) -> None:
    assert actor_type_for(inter) == expected


def test_split_associated_actors() -> None:
    assert split_actors("Journalists (Mexico); Labor Group (Mexico)") == [
        "Journalists (Mexico)",
        "Labor Group (Mexico)",
    ]
    assert split_actors(None) == []


def _slug(session: Session, actor_id: int) -> str:
    return session.get_one(Actor, actor_id).slug


@pytest.mark.parametrize(
    ("raw", "slug"),
    [
        ("Sinaloa Cartel", "cartel-de-sinaloa"),
        ("Cártel de Sinaloa (2018-)", "cartel-de-sinaloa"),
        ("CJNG: Jalisco New Generation Cartel", "cjng"),
        ("Jalisco New Generation Cartel - CJNG", "cjng"),
        ("CDN", "cartel-del-noreste"),
        ("Los Zetas", "cartel-del-noreste"),  # alias per the FTO notice
    ],
)
def test_resolve_known_cartels(seeded: Session, raw: str, slug: str) -> None:
    index = ActorIndex.load(seeded)
    assert _slug(seeded, index.resolve(raw, "Political militia")) == slug


def test_unknown_actor_created_once_and_reused(seeded: Session) -> None:
    index = ActorIndex.load(seeded)
    before = seeded.scalar(select(func.count()).select_from(Actor))
    a = index.resolve("Unidentified Armed Group (Mexico)", "Political militia")
    b = index.resolve("Unidentified Armed Group (Mexico)", "Political militia")
    assert a == b
    assert seeded.scalar(select(func.count()).select_from(Actor)) == before + 1
    actor = seeded.get_one(Actor, a)
    assert (actor.canonical_name, actor.actor_type) == ("Unidentified Armed Group", "armed_group")
    assert actor.sources[0]["publisher"].startswith("ACLED")


def test_faction_created_under_parent(seeded: Session) -> None:
    index = ActorIndex.load(seeded)
    faction_id = index.resolve("Sinaloa Cartel: Example Faction", "Political militia")
    faction = seeded.get_one(Actor, faction_id)
    parent = seeded.scalars(select(Actor).where(Actor.slug == "cartel-de-sinaloa")).one()
    assert (faction.canonical_name, faction.actor_type, faction.parent_id) == (
        "Example Faction",
        "faction",
        parent.id,
    )
    assert index.resolve("Sinaloa Cartel: Example Faction", None) == faction_id
