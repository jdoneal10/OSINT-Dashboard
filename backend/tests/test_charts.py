"""INTSUM chart service: spec validation, rendering and the fixed classification banner."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.reports.charts import CLASSIFICATION, TrendSpec, render_spec, to_bytes

TREND: dict[str, Any] = {
    "chart_type": "trend",
    "title": "Reported incidents rising",
    "source": "Synthetic test data",
    "dates": ["2026-09-05", "2026-09-12", "2026-09-19"],
    "series": [{"name": "Sonora", "values": [3, 5, 8]}],
}
CHANGE: dict[str, Any] = {
    "chart_type": "change",
    "title": "Activity shifting west",
    "source": "Synthetic test data",
    "categories": ["Nogales", "Ojinaga"],
    "pct_change": [12, -8],
}


def test_render_png_and_svg(client: TestClient) -> None:
    png = client.post("/charts/render", json=TREND)
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content.startswith(b"\x89PNG")

    svg = client.post("/charts/render", params={"fmt": "svg"}, json=CHANGE)
    assert svg.status_code == 200
    assert svg.headers["content-type"] == "image/svg+xml"
    assert CLASSIFICATION in svg.text  # svg.fonttype=none keeps text as text
    assert "▲" in svg.text  # increase/decrease shown by arrow, not color alone


def test_banner_cannot_be_changed_per_request(client: TestClient) -> None:
    svg = client.post(
        "/charts/render", params={"fmt": "svg", "classification": "CUI"}, json=CHANGE
    ).text
    assert CLASSIFICATION in svg
    assert ">CUI<" not in svg


def test_invalid_spec_is_rejected_before_drawing(client: TestClient) -> None:
    bad = TREND | {"series": [{"name": "Sonora", "values": [1, 2]}]}  # 2 values, 3 dates
    resp = client.post("/charts/render", json=bad)
    assert resp.status_code == 422
    assert "2 values for 3 dates" in resp.text
    assert client.post("/charts/render", json=TREND | {"chart_type": "pie"}).status_code == 422


def test_schema_lists_every_chart_type(client: TestClient) -> None:
    schema = client.get("/charts/schema").json()
    assert {"TrendSpec", "ComparisonSpec", "ChangeSpec"} <= set(schema["$defs"])


def test_more_than_eight_series_is_refused() -> None:
    with pytest.raises(ValidationError):
        TrendSpec(**TREND | {"series": [{"name": f"s{i}", "values": [1, 2, 3]} for i in range(9)]})


def test_dollar_signs_render_as_text() -> None:
    spec = TrendSpec(**TREND | {"title": "Seizures worth $5 million and $2 million"})
    assert to_bytes(render_spec(spec), "png").startswith(b"\x89PNG")
