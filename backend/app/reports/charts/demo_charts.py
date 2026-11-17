"""Render one sample of each chart type with NOTIONAL data, to check the template.

    cd backend && uv run python -m app.reports.charts.demo_charts

Writes PNGs to ``data/chart_samples/`` (gitignored). The data is made up.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.config import get_settings
from app.reports.charts import (
    ChangeSpec,
    ChartSpec,
    ComparisonSpec,
    IntsumStyle,
    Series,
    TrendSpec,
    render_spec,
    to_bytes,
)

OUT = get_settings().reference_dir.parent / "chart_samples"
style = IntsumStyle(extra_footer="NOTIONAL DATA FOR TEMPLATE TESTING")

days = [date(2026, 9, 1) + timedelta(days=7 * i) for i in range(12)]

samples: dict[str, ChartSpec] = {
    "trend": TrendSpec(
        title="Reported smuggling incidents rising in Sonora corridor",
        subtitle="Weekly OSINT-reported incidents by border sector, Sep to Nov 2026",
        source="Notional OSINT aggregation",
        dates=days,
        series=[
            Series(name="Sonora", values=[22, 25, 24, 28, 31, 30, 35, 38, 36, 41, 44, 47]),
            Series(name="Chihuahua", values=[30, 29, 31, 28, 27, 29, 26, 27, 25, 26, 24, 25]),
            Series(name="Tamaulipas", values=[18, 20, 19, 21, 23, 22, 21, 24, 23, 25, 24, 26]),
        ],
        y_label="Incidents per week",
    ),
    "comparison": ComparisonSpec(
        title="Manzanillo leads notional precursor seizure reports",
        subtitle="Reported precursor chemical seizure events by Mexican port, last 90 days",
        source="Notional OSINT aggregation",
        categories=[
            "Manzanillo",
            "Lázaro Cárdenas",
            "Veracruz",
            "Ensenada",
            "Altamira",
            "Topolobampo",
        ],
        values=[41, 33, 17, 12, 9, 6],
        value_label="events",
        highlight="Manzanillo",
    ),
    "change": ChangeSpec(
        title="Activity shifting west along notional smuggling routes",
        subtitle="Change in reported route activity, Oct vs Sep 2026",
        source="Notional OSINT aggregation",
        categories=[
            "Sonoyta-Lukeville",
            "Nogales",
            "Agua Prieta",
            "Ciudad Juárez",
            "Ojinaga",
            "Piedras Negras",
            "Reynosa",
        ],
        pct_change=[38, 21, 9, -4, -12, -18, 3],
    ),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in samples.items():
        path = OUT / f"sample_{name}.png"
        path.write_bytes(to_bytes(render_spec(spec, style=style), "png"))
        print("wrote", path)


if __name__ == "__main__":
    main()
