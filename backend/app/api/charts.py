"""INTSUM chart rendering (merged from intsum-charts, 2026-11-16).

POST /charts/render   a chart spec as JSON -> PNG or SVG
GET  /charts/schema   JSON schema for specs (for the analytic layer's prompts)

The classification banner is fixed to the project marking; it cannot be set per request.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import TypeAdapter

from app.reports.charts import ChartSpec, render_spec, to_bytes

router = APIRouter(prefix="/charts", tags=["charts"])

_spec_adapter: TypeAdapter[ChartSpec] = TypeAdapter(ChartSpec)
_MEDIA = {"png": "image/png", "svg": "image/svg+xml"}


@router.post("/render")
async def render_chart(
    spec: Annotated[ChartSpec, Body()],
    fmt: Annotated[Literal["png", "svg"], Query()] = "png",
) -> Response:
    # Drawing is CPU work; run it off the event loop so the API stays responsive.
    image = await run_in_threadpool(lambda: to_bytes(render_spec(spec), fmt))
    return Response(content=image, media_type=_MEDIA[fmt])


@router.get("/schema")
def chart_schema() -> dict[str, Any]:
    return _spec_adapter.json_schema()
