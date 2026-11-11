"""Load cited reference data from ``data/reference/`` into PostGIS. Idempotent.

Files (each optional; missing files are skipped with a warning):
- ``aoi_*.geojson``      → ``reference_areas`` (upsert on slug)
- ``nodes.geojson``      → ``nodes`` (upsert on slug)
- ``actor_aliases.yaml`` → ``actors`` + ``actor_aliases`` (upsert; aliases are synced
  per actor, so an alias removed from the YAML is removed from the database)

Validation runs over every file before anything is written; an uncited entry aborts the load.

Run: ``uv run python -m app.reference.load`` (or ``make seed``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Actor, ActorAlias, Node, ReferenceArea
from app.db.session import session_factory
from app.reference.normalize import normalize_alias
from app.reference.schemas import (
    ActorFile,
    AliasEntry,
    AreaCollection,
    Geometry,
    NodeCollection,
)

log = logging.getLogger(__name__)


class ReferenceDataError(ValueError):
    """Reference data failed validation; nothing was written."""


@dataclass
class LoadReport:
    areas: int = 0
    nodes: int = 0
    actors: int = 0
    aliases: int = 0
    skipped_files: list[str] = field(default_factory=list)


@dataclass
class _Parsed:
    areas: list[AreaCollection] = field(default_factory=list)
    nodes: NodeCollection | None = None
    actors: ActorFile | None = None


def _ewkt(geom: BaseGeometry) -> Any:
    return func.ST_GeogFromText(f"SRID=4326;{geom.wkt}")


def _to_shape(geometry: Geometry, where: str) -> BaseGeometry:
    geom = shape(geometry.model_dump())
    if not geom.is_valid:
        raise ReferenceDataError(f"{where}: invalid geometry")
    return geom


def _as_multipolygon(geom: BaseGeometry, where: str) -> MultiPolygon:
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    raise ReferenceDataError(f"{where}: expected Polygon or MultiPolygon, got {geom.geom_type}")


def parse_reference_dir(ref_dir: Path) -> tuple[_Parsed, list[str]]:
    """Validate every reference file. Raises ``ReferenceDataError`` on the first bad file."""
    parsed = _Parsed()
    skipped: list[str] = []

    def _read(path: Path) -> Any:
        try:
            text = path.read_text(encoding="utf-8")
            return yaml.safe_load(text) if path.suffix in {".yaml", ".yml"} else json.loads(text)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ReferenceDataError(f"{path.name}: unreadable ({exc})") from exc

    def _validate[M](model: type[M], path: Path) -> M:
        try:
            return model.model_validate(_read(path))  # type: ignore[attr-defined,no-any-return]
        except ReferenceDataError:
            raise
        except ValueError as exc:  # pydantic.ValidationError subclasses ValueError
            raise ReferenceDataError(f"{path.name}: {exc}") from exc

    aoi_files = sorted(ref_dir.glob("aoi_*.geojson"))
    if not aoi_files:
        skipped.append("aoi_*.geojson")
    parsed.areas = [_validate(AreaCollection, p) for p in aoi_files]

    nodes_path = ref_dir / "nodes.geojson"
    if nodes_path.is_file():
        parsed.nodes = _validate(NodeCollection, nodes_path)
    else:
        skipped.append(nodes_path.name)

    actors_path = ref_dir / "actor_aliases.yaml"
    if actors_path.is_file():
        parsed.actors = _validate(ActorFile, actors_path)
        slugs = {a.slug for a in parsed.actors.actors}
        for actor in parsed.actors.actors:
            if actor.parent and actor.parent not in slugs:
                raise ReferenceDataError(
                    f"{actors_path.name}: {actor.slug} has unknown parent {actor.parent!r}"
                )
    else:
        skipped.append(actors_path.name)

    _check_unique([f.properties.slug for c in parsed.areas for f in c.features], "area slug")
    if parsed.nodes:
        _check_unique([f.properties.slug for f in parsed.nodes.features], "node slug")
    return parsed, skipped


def _check_unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for v in values:
        if v in seen:
            raise ReferenceDataError(f"duplicate {label}: {v}")
        seen.add(v)


def _load_areas(session: Session, collections: list[AreaCollection]) -> int:
    count = 0
    for collection in collections:
        for feature in collection.features:
            p = feature.properties
            geom = _as_multipolygon(_to_shape(feature.geometry, p.slug), p.slug)
            values = {
                "slug": p.slug,
                "name": p.name,
                "area_type": p.area_type,
                "country_iso3": p.country_iso3,
                "admin1_code": p.admin1_code,
                "phase": p.phase,
                "geom": _ewkt(geom),
                "sources": [c.model_dump(mode="json") for c in p.sources],
            }
            stmt = insert(ReferenceArea).values(**values)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[ReferenceArea.slug],
                    set_={k: stmt.excluded[k] for k in values if k != "slug"}
                    | {"updated_at": func.now()},
                )
            )
            count += 1
    return count


def _load_nodes(session: Session, collection: NodeCollection) -> int:
    for feature in collection.features:
        p = feature.properties
        point: BaseGeometry | None = None
        area: MultiPolygon | None = None
        if feature.geometry is not None:
            geom = _to_shape(feature.geometry, p.slug)
            if feature.geometry.type == "Point":
                point = geom
            else:
                area = _as_multipolygon(geom, p.slug)
                point = area.representative_point()
        values = {
            "slug": p.slug,
            "name": p.name,
            "node_type": p.node_type,
            "code": p.code,
            "country_iso3": p.country_iso3,
            "admin1_code": p.admin1_code,
            "point": _ewkt(point) if point is not None else None,
            "area": _ewkt(area) if area is not None else None,
            "properties": p.attributes,
            "sources": [c.model_dump(mode="json") for c in p.sources],
        }
        stmt = insert(Node).values(**values)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Node.slug],
                set_={k: stmt.excluded[k] for k in values if k != "slug"}
                | {"updated_at": func.now()},
            )
        )
    return len(collection.features)


def _load_actors(session: Session, actor_file: ActorFile) -> tuple[int, int]:
    alias_count = 0
    ids: dict[str, int] = {}
    # Two passes so a parent may appear after its child in the file.
    for actor in actor_file.actors:
        values = {
            "slug": actor.slug,
            "canonical_name": actor.canonical_name,
            "actor_type": actor.actor_type,
            "country_iso3": actor.country_iso3,
            "description": actor.description,
            "sources": [c.model_dump(mode="json") for c in actor.sources],
        }
        stmt = insert(Actor).values(**values)
        actor_id = session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Actor.slug],
                set_={k: stmt.excluded[k] for k in values if k != "slug"}
                | {"updated_at": func.now()},
            ).returning(Actor.id)
        ).scalar_one()
        ids[actor.slug] = actor_id

    for actor in actor_file.actors:
        actor_id = ids[actor.slug]
        session.execute(
            update(Actor)
            .where(Actor.id == actor_id)
            .values(parent_id=ids[actor.parent] if actor.parent else None)
        )
        wanted: dict[str, tuple[str, str | None]] = {}
        for entry in [*actor.alias_entries(), AliasEntry(alias=actor.canonical_name)]:
            key = normalize_alias(entry.alias)
            if key and key not in wanted:
                wanted[key] = (entry.alias, entry.language)
        session.execute(
            delete(ActorAlias).where(
                ActorAlias.actor_id == actor_id,
                ActorAlias.alias_normalized.not_in(list(wanted)),
            )
        )
        citations = [c.model_dump(mode="json") for c in actor.sources]
        for key, (alias, language) in wanted.items():
            stmt = insert(ActorAlias).values(
                actor_id=actor_id,
                alias=alias,
                alias_normalized=key,
                language=language,
                sources=citations,
            )
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_actor_aliases_actor_id_alias_normalized",
                    set_={
                        "alias": stmt.excluded.alias,
                        "language": stmt.excluded.language,
                        "sources": stmt.excluded.sources,
                        "updated_at": func.now(),
                    },
                )
            )
        alias_count += len(wanted)
    return len(actor_file.actors), alias_count


def load_reference(session: Session, ref_dir: Path) -> LoadReport:
    """Validate everything first, then write in the caller's transaction."""
    parsed, skipped = parse_reference_dir(ref_dir)
    report = LoadReport(skipped_files=skipped)
    report.areas = _load_areas(session, parsed.areas)
    if parsed.nodes:
        report.nodes = _load_nodes(session, parsed.nodes)
    if parsed.actors:
        report.actors, report.aliases = _load_actors(session, parsed.actors)
    return report


def table_counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
        for model in (ReferenceArea, Node, Actor, ActorAlias)
    }


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        with session_factory()() as session, session.begin():
            report = load_reference(session, settings.reference_dir)
            counts = table_counts(session)
    except ReferenceDataError as exc:
        log.error("reference data rejected, nothing written: %s", exc)
        return 1
    for name in report.skipped_files:
        log.warning("skipped missing reference file: %s", name)
    log.info(
        "loaded %d areas, %d nodes, %d actors, %d aliases; table totals %s",
        report.areas,
        report.nodes,
        report.actors,
        report.aliases,
        counts,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
