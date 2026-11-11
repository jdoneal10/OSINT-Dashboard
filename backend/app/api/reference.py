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
    geometry: dict[str, Any]
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
    """Area-of-interest polygons for the given phase (and earlier phases)."""
    rows = session.execute(
        select(ReferenceArea, _geojson(ReferenceArea.geom))
        .where(ReferenceArea.phase <= phase)
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
                    "sources": area.sources,
                },
            )
            for area, geom in rows
        ]
    )


@router.get("/nodes", response_model=FeatureCollection)
def nodes(
    session: Annotated[Session, Depends(get_session)],
    node_type: Annotated[list[str] | None, Query()] = None,
) -> FeatureCollection:
    """Corridor nodes. Area nodes (e.g. USBP sectors) return their polygon plus a label point."""
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
                geometry=json.loads(geom),
                properties={
                    "slug": node.slug,
                    "name": node.name,
                    "node_type": node.node_type,
                    "code": node.code,
                    "country_iso3": node.country_iso3,
                    "admin1_code": node.admin1_code,
                    "label_point": [round(x, _PRECISION), round(y, _PRECISION)],
                    "attributes": node.properties,
                    "sources": node.sources,
                },
            )
            for node, geom, x, y in rows
        ]
    )
