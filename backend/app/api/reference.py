"""Reference layers as GeoJSON, read from PostGIS."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from geoalchemy2 import Geometry
from pydantic import BaseModel
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.db.models import NODE_TYPES, Node, ReferenceArea
from app.db.session import get_session

router = APIRouter(prefix="/reference", tags=["reference"])

_PRECISION = 5  # ~1 m; plenty for reference layers and keeps payloads small


class Feature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: dict[str, Any] | None
    properties: dict[str, Any]


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Feature]


def _geojson(column: Any) -> Any:
    return func.ST_AsGeoJSON(cast(column, Geometry), _PRECISION)


@router.get("/aoi", response_model=FeatureCollection)
def aoi(
    session: Annotated[Session, Depends(get_session)],
    phase: Annotated[int, Query(ge=1, le=5)] = 1,
) -> FeatureCollection:
    """State-level (admin1) area-of-interest polygons for the given phase and earlier ones,
    each with a ``label_point`` (one per area, so multi-part states get a single label).
    Municipalities are served separately by ``/reference/municipalities``."""
    label = func.ST_PointOnSurface(cast(ReferenceArea.geom, Geometry))
    rows = session.execute(
        select(ReferenceArea, _geojson(ReferenceArea.geom), func.ST_X(label), func.ST_Y(label))
        .where(ReferenceArea.phase <= phase, ReferenceArea.area_type == "admin1")
        .order_by(ReferenceArea.country_iso3, ReferenceArea.name)
    ).all()
    return FeatureCollection(
        features=[
            Feature(
                id=area.slug,
                geometry=json.loads(geom),
                properties={
                    "slug": area.slug,
                    "name": area.name,
                    "area_type": area.area_type,
                    "country_iso3": area.country_iso3,
                    "admin1_code": area.admin1_code,
                    "phase": area.phase,
                    "label_point": [round(x, _PRECISION), round(y, _PRECISION)],
                    "sources": area.sources,
                },
            )
            for area, geom, x, y in rows
        ]
    )


MUNICIPAL_TOLERANCE = 0.004  # degrees (~400 m): national choropleth, not boundary analysis


@router.get("/municipalities", response_model=FeatureCollection)
def municipalities(
    session: Annotated[Session, Depends(get_session)],
    admin1: Annotated[list[str] | None, Query(description="e.g. MX-SIN")] = None,
) -> FeatureCollection:
    """Mexican municipalities (INEGI) simplified for choropleths. Feature id = cvegeo."""
    geom = func.ST_AsGeoJSON(
        func.ST_SimplifyPreserveTopology(cast(ReferenceArea.geom, Geometry), MUNICIPAL_TOLERANCE),
        3,
    )
    stmt = select(
        ReferenceArea.admin2_code, ReferenceArea.name, ReferenceArea.admin1_code, geom
    ).where(ReferenceArea.area_type == "admin2", ReferenceArea.admin2_code.is_not(None))
    if admin1:
        stmt = stmt.where(ReferenceArea.admin1_code.in_(admin1))
    rows = session.execute(stmt.order_by(ReferenceArea.admin2_code)).all()
    return FeatureCollection(
        features=[
            Feature(
                id=code,
                geometry=json.loads(g),
                properties={"code": code, "name": name, "admin1_code": a1},
            )
            for code, name, a1, g in rows
        ]
    )


@router.get("/nodes", response_model=FeatureCollection)
def nodes(
    session: Annotated[Session, Depends(get_session)],
    node_type: Annotated[list[str] | None, Query()] = None,
) -> FeatureCollection:
    """Corridor nodes. Area nodes return their polygon plus a label point; nodes with no
    public geometry (USBP sectors, ADR 0002) return ``geometry: null``."""
    stmt = select(
        Node,
        _geojson(func.coalesce(Node.area, Node.point)),
        func.ST_X(cast(Node.point, Geometry)),
        func.ST_Y(cast(Node.point, Geometry)),
    ).order_by(Node.node_type, Node.name)
    if node_type:
        stmt = stmt.where(Node.node_type.in_([t for t in node_type if t in NODE_TYPES]))
    rows = session.execute(stmt).all()
    return FeatureCollection(
        features=[
            Feature(
                id=node.slug,
                geometry=json.loads(geom) if geom is not None else None,
                properties={
                    "slug": node.slug,
                    "name": node.name,
                    "node_type": node.node_type,
                    "code": node.code,
                    "country_iso3": node.country_iso3,
                    "admin1_code": node.admin1_code,
                    "label_point": (
                        [round(x, _PRECISION), round(y, _PRECISION)] if x is not None else None
                    ),
                    "attributes": node.properties,
                    "sources": node.sources,
                },
            )
            for node, geom, x, y in rows
        ]
    )


class AdjacencyOut(BaseModel):
    sector: str
    name: str
    adjacent_admin1: list[str]
    field_office: str | None
    method: str | None
    sources: list[dict[str, Any]]


@router.get("/adjacency", response_model=list[AdjacencyOut])
def adjacency(session: Annotated[Session, Depends(get_session)]) -> list[AdjacencyOut]:
    """USBP sector -> adjacent Mexican states and paired OFO field office (analyst-derived)."""
    rows = session.scalars(
        select(Node).where(Node.node_type == "usbp_sector").order_by(Node.name)
    ).all()
    return [
        AdjacencyOut(
            sector=n.slug,
            name=n.name,
            adjacent_admin1=n.properties.get("adjacent_admin1", []),
            field_office=n.properties.get("field_office"),
            method=n.properties.get("adjacency_method"),
            sources=n.properties.get("adjacency_sources", []),
        )
        for n in rows
    ]
