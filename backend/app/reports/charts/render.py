"""
Chart renderers.

Each function takes a validated spec and returns a matplotlib Figure already
framed with the INTSUM template. `render_spec` dispatches on chart_type, and
`to_bytes` turns any figure into PNG or SVG for the API or the report builder.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Literal

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.text import Annotation

from . import style as S  # noqa: N812 - short alias for the template module
from .specs import ChangeSpec, ComparisonSpec, TrendSpec

AnySpec = TrendSpec | ComparisonSpec | ChangeSpec

ImageFormat = Literal["png", "svg"]


# ---------------------------------------------------------------------------
# Trend: change over time
# ---------------------------------------------------------------------------


def trend(
    spec: TrendSpec, *, as_of: datetime | None = None, style: S.IntsumStyle = S.DEFAULT_STYLE
) -> Figure:
    fig, ax = S.new_figure(style)
    n = len(spec.series)
    x = mdates.date2num(spec.dates)  # type: ignore[no-untyped-call]

    for i, s in enumerate(spec.series):
        color = S.series_color(i)
        ax.plot(x, s.values, color=color, label=S.plain(s.name), zorder=3)
        # Marker and direct label on the latest point only (no number on every point)
        ax.scatter(
            [x[-1]],
            [s.values[-1]],
            s=28,
            color=color,
            edgecolor=S.SURFACE,
            linewidth=1.5,
            zorder=4,
            clip_on=False,
        )
        if n <= 4:
            ax.annotate(
                f"{S.plain(s.name)}  {s.values[-1]:,.0f}",
                (x[-1], s.values[-1]),
                xytext=(8, 0),
                textcoords="offset points",
                va="center",
                fontsize=style.fonts["label"],
                color=S.INK_PRIMARY,
            )

    top = max(max(s.values) for s in spec.series)
    ax.set_ylim(0, top * 1.12)
    ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))  # type: ignore[no-untyped-call]
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))  # type: ignore[no-untyped-call]
    ax.spines["bottom"].set_color(S.BASELINE)
    ax.tick_params(labelsize=style.fonts["axis"])
    if spec.y_label:
        ax.set_ylabel(spec.y_label, fontsize=style.fonts["axis"])
    # Leave room on the right for end labels
    ax.set_xlim(x[0], x[-1])
    ax.margins(x=0)
    fig.axes[0].set_position((0.075, S.PLOT_BOTTOM, 0.74, S.PLOT_TOP - S.PLOT_BOTTOM))

    if n >= 2:
        _legend(ax, style)
    _nudge_end_labels(ax)

    return S.frame_figure(
        fig, title=spec.title, subtitle=spec.subtitle, source=spec.source, as_of=as_of, style=style
    )


def _nudge_end_labels(ax: Axes, min_gap_pts: float = 11) -> None:
    """Push end-of-line labels apart vertically so they never overlap."""
    labels = [t for t in ax.texts if isinstance(t, Annotation)]
    if len(labels) < 2:
        return
    ax.figure.canvas.draw()
    trans = ax.transData
    ys = [trans.transform((0, t.xy[1]))[1] for t in labels]
    order = sorted(range(len(labels)), key=lambda i: ys[i])
    gap_px = min_gap_pts * ax.figure.dpi / 72
    placed: list[float] = []
    for i in order:
        y = ys[i]
        if placed and y - placed[-1] < gap_px:
            y = placed[-1] + gap_px
        placed.append(y)
        labels[i].set_position((8, (y - ys[i]) * 72 / ax.figure.dpi))


# ---------------------------------------------------------------------------
# Comparison: magnitude across categories (horizontal bars)
# ---------------------------------------------------------------------------


def comparison(
    spec: ComparisonSpec, *, as_of: datetime | None = None, style: S.IntsumStyle = S.DEFAULT_STYLE
) -> Figure:
    fig, ax = S.new_figure(style)

    pairs = list(zip((S.plain(c) for c in spec.categories), spec.values, strict=True))
    if spec.sort:
        pairs.sort(key=lambda p: p[1])  # largest ends up on top
    cats, vals = zip(*pairs, strict=True)

    base = S.series_color(0)
    highlight = S.plain(spec.highlight) if spec.highlight else None
    colors = [base if (highlight is None or c == highlight) else S.BASELINE for c in cats]

    bars = ax.barh(
        cats, vals, height=0.62, color=colors, edgecolor=S.SURFACE, linewidth=1.0, zorder=3
    )

    # Value labels just past each bar end
    for bar, v in zip(bars, vals, strict=True):
        ax.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2,
            f"  {v:,.0f}",
            va="center",
            ha="left",
            fontsize=style.fonts["label"],
            color=S.INK_PRIMARY,
        )

    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color(S.BASELINE)
    ax.spines["bottom"].set_visible(False)
    ax.set_xlim(0, max(vals) * 1.12)
    ax.xaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    ax.tick_params(labelsize=style.fonts["axis"])
    if spec.value_label:
        ax.set_xlabel(spec.value_label.capitalize(), fontsize=style.fonts["axis"])

    # Category labels can be long; give them room
    longest = max(len(c) for c in cats)
    left = min(0.075 + longest * 0.0072, 0.32)
    ax.set_position((left, S.PLOT_BOTTOM + 0.02, 0.925 - left, S.PLOT_TOP - S.PLOT_BOTTOM - 0.02))

    return S.frame_figure(
        fig, title=spec.title, subtitle=spec.subtitle, source=spec.source, as_of=as_of, style=style
    )


# ---------------------------------------------------------------------------
# Change: diverging bars around zero
# ---------------------------------------------------------------------------


def change(
    spec: ChangeSpec, *, as_of: datetime | None = None, style: S.IntsumStyle = S.DEFAULT_STYLE
) -> Figure:
    fig, ax = S.new_figure(style)

    pairs = sorted(
        zip((S.plain(c) for c in spec.categories), spec.pct_change, strict=True),
        key=lambda p: p[1],
    )
    cats, vals = zip(*pairs, strict=True)
    colors = [S.DIVERGE_UP if v > 0 else S.DIVERGE_DOWN if v < 0 else S.BASELINE for v in vals]

    bars = ax.barh(
        cats, vals, height=0.62, color=colors, edgecolor=S.SURFACE, linewidth=1.0, zorder=3
    )
    ax.axvline(0, color=S.INK_SECONDARY, linewidth=1.0, zorder=4)

    span = max(abs(v) for v in vals) or 1
    for bar, v in zip(bars, vals, strict=True):
        ha, pad = ("left", span * 0.02) if v >= 0 else ("right", -span * 0.02)
        arrow = "▲ " if v > 0 else "▼ " if v < 0 else ""
        ax.text(
            v + pad,
            bar.get_y() + bar.get_height() / 2,
            f"{arrow}{v:+.0f}%",
            va="center",
            ha=ha,
            fontsize=style.fonts["label"],
            color=S.INK_PRIMARY,
        )

    lo, hi = min(*vals, 0), max(*vals, 0)
    ax.set_xlim(lo - span * 0.22 if lo < 0 else 0, hi + span * 0.22 if hi > 0 else 0)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.spines["bottom"].set_visible(False)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:+.0f}%" if x else "0"))
    ax.tick_params(labelsize=style.fonts["axis"])

    longest = max(len(c) for c in cats)
    left = min(0.075 + longest * 0.0072, 0.32)
    ax.set_position((left, S.PLOT_BOTTOM + 0.02, 0.925 - left, S.PLOT_TOP - S.PLOT_BOTTOM - 0.02))

    # Small key so increase/decrease is never color-alone
    ax.text(
        1.0,
        1.03,
        "▲ increase   ▼ decrease",
        transform=ax.transAxes,
        ha="right",
        fontsize=style.fonts["label"],
        color=S.INK_SECONDARY,
    )
    return S.frame_figure(
        fig, title=spec.title, subtitle=spec.subtitle, source=spec.source, as_of=as_of, style=style
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _legend(ax: Axes, style: S.IntsumStyle) -> None:
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(0, 1.0),
        ncol=4,
        fontsize=style.fonts["label"],
        handlelength=1.6,
        columnspacing=1.4,
        labelcolor=S.INK_SECONDARY,
        borderaxespad=0.2,
    )


RENDERERS = {"trend": trend, "comparison": comparison, "change": change}


def render_spec(
    spec: AnySpec, *, as_of: datetime | None = None, style: S.IntsumStyle = S.DEFAULT_STYLE
) -> Figure:
    """Draw any validated spec."""
    if isinstance(spec, TrendSpec):
        return trend(spec, as_of=as_of, style=style)
    if isinstance(spec, ComparisonSpec):
        return comparison(spec, as_of=as_of, style=style)
    return change(spec, as_of=as_of, style=style)


def to_bytes(fig: Figure, fmt: ImageFormat = "png") -> bytes:
    """Serialize a figure and free its memory."""
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
