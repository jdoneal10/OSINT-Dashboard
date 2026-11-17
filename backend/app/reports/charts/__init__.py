"""INTSUM chart service: validated specs drawn with one shared template.

Merged from the owner's intsum-charts package on 2026-11-16. Import from here, not from
the submodules:

    from app.reports.charts import TrendSpec, render_spec, to_bytes
    png = to_bytes(render_spec(TrendSpec(**spec_dict)), "png")

Charts are deterministic: something produces a spec (the analytic layer or a dashboard
control), pydantic validates it, and ``render_spec`` draws it. The banner is fixed to the
project classification.
"""

from .render import render_spec, to_bytes
from .specs import ChangeSpec, ChartSpec, ComparisonSpec, Series, TrendSpec
from .style import CLASSIFICATION, DEFAULT_STYLE, IntsumStyle

__all__ = [
    "CLASSIFICATION",
    "DEFAULT_STYLE",
    "ChangeSpec",
    "ChartSpec",
    "ComparisonSpec",
    "IntsumStyle",
    "Series",
    "TrendSpec",
    "render_spec",
    "to_bytes",
]
