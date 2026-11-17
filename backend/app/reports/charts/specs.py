"""
Chart specs: the small, structured description of a chart.

The analytic layer (or Qwen3, or a person in the dashboard) never draws anything.
It fills in one of these specs, and render.py turns the spec into an image.
Because the spec is validated by Pydantic, a bad LLM output is rejected with a
clear error before any drawing happens.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

# Caps keep a bad or hostile spec from tying up the renderer (weekly series over ~20 years).
MAX_POINTS = 1100


class BaseSpec(BaseModel):
    title: str = Field(..., max_length=90, description="The takeaway, stated as a finding.")
    subtitle: str | None = Field(None, max_length=140, description="Scope, units, timeframe.")
    source: str = Field(..., description="Where the data came from.")


class Series(BaseModel):
    name: str = Field(..., max_length=60)
    values: list[float] = Field(..., min_length=1, max_length=MAX_POINTS)


class TrendSpec(BaseSpec):
    """Change over time. One to four series reads best."""

    chart_type: Literal["trend"] = "trend"
    dates: list[date] = Field(..., min_length=1, max_length=MAX_POINTS)
    series: list[Series] = Field(..., min_length=1, max_length=8)
    y_label: str | None = None

    @model_validator(mode="after")
    def _lengths_match(self) -> Self:
        for s in self.series:
            if len(s.values) != len(self.dates):
                raise ValueError(
                    f"Series '{s.name}' has {len(s.values)} values for {len(self.dates)} dates."
                )
        return self


class ComparisonSpec(BaseSpec):
    """Magnitude across categories (regions, groups, ports)."""

    chart_type: Literal["comparison"] = "comparison"
    categories: list[str] = Field(..., min_length=1, max_length=15)
    values: list[float] = Field(..., max_length=15)
    value_label: str | None = Field(None, description="Unit for the values, e.g. 'incidents'.")
    highlight: str | None = Field(None, description="Category to emphasize; others render muted.")
    sort: bool = True

    @model_validator(mode="after")
    def _lengths_match(self) -> Self:
        if len(self.categories) != len(self.values):
            raise ValueError("categories and values must be the same length.")
        if self.highlight and self.highlight not in self.categories:
            raise ValueError(f"highlight '{self.highlight}' is not one of the categories.")
        return self


class ChangeSpec(BaseSpec):
    """Period-over-period change (e.g. route activity this month vs last)."""

    chart_type: Literal["change"] = "change"
    categories: list[str] = Field(..., min_length=1, max_length=15)
    pct_change: list[float] = Field(..., max_length=15)

    @model_validator(mode="after")
    def _lengths_match(self) -> Self:
        if len(self.categories) != len(self.pct_change):
            raise ValueError("categories and pct_change must be the same length.")
        return self


# One type that accepts any of the specs, picked by the chart_type field.
ChartSpec = Annotated[TrendSpec | ComparisonSpec | ChangeSpec, Field(discriminator="chart_type")]
