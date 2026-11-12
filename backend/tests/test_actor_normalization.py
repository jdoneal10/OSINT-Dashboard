from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Actor, ActorAlias
from app.enrich.actors import (
    ActorIndex,
    actor_type_for,
    clean_name,
    prune_unlinked,
    split_actors,
)


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


def _ancestors(session: Session, actor_id: int) -> list[str]:
    chain, actor = [], session.get_one(Actor, actor_id)
    while actor.parent_id is not None:
        actor = session.get_one(Actor, actor.parent_id)
        chain.append(actor.slug)
    return chain


@pytest.mark.parametrize(
    ("raw", "slug", "ancestors"),
    [
        ("Los Chapitos Gang (Mexico)", "los-chapitos", ["cartel-de-sinaloa"]),
        ("Gente Nueva Gang", "gente-nueva", ["los-chapitos", "cartel-de-sinaloa"]),
        ("Los Rusos Gang", "los-rusos", ["mayiza", "cartel-de-sinaloa"]),
        ("La Linea Gang", "la-linea", ["cartel-de-juarez"]),
        ("Los Metros Gang", "los-metros", ["cartel-del-golfo"]),
        ("Tropa del Infierno Gang", "tropa-del-infierno", ["cartel-del-noreste"]),
        # Cited allies / independents carry no parent.
        ("Los Aztecas Gang", "barrio-azteca", []),
        ("Los Zetas Vieja Escuela Gang", "zetas-vieja-escuela", []),
        ("Juarez Cartel", "cartel-de-juarez", []),
        ("NCDJ: New Juarez Cartel", "nuevo-cartel-de-juarez", []),
    ],
)
def test_resolve_cited_factions(seeded: Session, raw: str, slug: str, ancestors: list[str]) -> None:
    actor_id = ActorIndex.load(seeded).resolve(raw, "Political militia")
    assert _slug(seeded, actor_id) == slug
    assert _ancestors(seeded, actor_id) == ancestors


def test_curated_alias_beats_acled_created_actor(seeded: Session) -> None:
    """An ACLED-created actor that owns the same alias (made before the cited entry existed)
    must not capture the link; the curated faction wins whatever the row order."""
    stale = ActorIndex.load(seeded).create("Stale Linea", "Stale Linea", "armed_group")
    seeded.add(
        ActorAlias(
            actor_id=stale,
            alias="La Linea Gang",
            alias_normalized="la linea gang",
            sources=seeded.get_one(Actor, stale).sources,
        )
    )
    seeded.flush()
    index = ActorIndex.load(seeded)
    assert _slug(seeded, index.resolve("La Linea Gang", "Political militia")) == "la-linea"
    assert stale != index.match("La Linea Gang")


def test_prune_unlinked_drops_only_orphaned_acled_actors(seeded: Session) -> None:
    index = ActorIndex.load(seeded)
    orphan = index.create("Orphan Gang", "Orphan Gang", "armed_group")
    parent = index.create("Orphan Parent Gang", "Orphan Parent Gang", "armed_group")
    index.create("Orphan Child Faction", "Orphan Child Faction", "faction", parent_id=parent)
    seeded.flush()
    # Child goes first, then its now-childless parent, then nothing.
    assert prune_unlinked(seeded) == 2
    assert prune_unlinked(seeded) == 1
    assert prune_unlinked(seeded) == 0
    seeded.expire_all()
    assert seeded.get(Actor, orphan) is None
    assert seeded.get(Actor, parent) is None
    # Curated actors with no events (e.g. mayiza) are never pruned.
    assert seeded.scalars(select(Actor).where(Actor.slug == "mayiza")).one_or_none() is not None
