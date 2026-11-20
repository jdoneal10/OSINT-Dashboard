"""
INTSUM chart style template (merged from intsum-charts, 2026-11-16).

Every chart the backend draws goes through this module, so the dashboard and the
automated INTSUMs share one look: same fonts, colors, classification banners,
title block, and source/date footer.

Change the look here, in one place. Renderers in render.py never hard-code colors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import matplotlib

matplotlib.use("Agg")  # headless rendering, no display needed on the server
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

# ---------------------------------------------------------------------------
# Palette (validated for color-vision deficiency; keep the ORDER, it matters)
# ---------------------------------------------------------------------------

# Categorical series colors. Assign in this fixed order and never cycle.
# Past 8 series, fold the rest into "Other" or split into small multiples.
SERIES = [
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#6250d6",  # 7 violet
    "#e34948",  # 8 red
]

# Diverging pair for "increase vs decrease" charts (two poles, gray midpoint).
DIVERGE_UP = "#e34948"  # red  = increase in threat activity
DIVERGE_DOWN = "#2a78d6"  # blue = decrease
DIVERGE_MID = "#f0efec"

# Ink and chrome
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

FONT_STACK = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]

# Classification banner. This project holds UNCLASSIFIED open-source information only
# (CLAUDE.md hard rules 1 and 7), so the banner text and color are fixed, not settable.
CLASSIFICATION = "UNCLASSIFIED — OPEN-SOURCE INFORMATION ONLY"
BANNER_BG, BANNER_FG = "#007a33", "#ffffff"


# ---------------------------------------------------------------------------
# Report-level settings
# ---------------------------------------------------------------------------


@dataclass
class IntsumStyle:
    """Settings shared by every chart in a product."""

    product_line: str = "OSINT DASHBOARD | INTSUM"
    width_in: float = 10.0
    height_in: float = 5.6
    dpi: int = 200
    show_generated_stamp: bool = True
    extra_footer: str | None = None  # e.g. "NOTIONAL DATA FOR TRAINING"
    _fonts: dict[str, float] = field(
        default_factory=lambda: {
            "title": 15,
            "subtitle": 10.5,
            "axis": 9,
            "label": 9,
            "footer": 7.5,
            "banner": 8.5,
        }
    )

    @property
    def fonts(self) -> dict[str, float]:
        return self._fonts


DEFAULT_STYLE = IntsumStyle()


def series_color(index: int) -> str:
    """Color for the Nth series. Raises past 8 instead of inventing a color."""
    if index >= len(SERIES):
        raise ValueError(
            f"{index + 1} series requested; max is {len(SERIES)}. "
            "Fold extras into 'Other' or use small multiples."
        )
    return SERIES[index]


def apply_rcparams() -> None:
    """Global matplotlib defaults. Called once on import."""
    plt.rcParams.update(
        {
            # A list of families turns on per-glyph fallback: Helvetica Neue has no ▲/▼, so
            # those come from DejaVu Sans instead of rendering as empty boxes.
            "font.family": FONT_STACK,
            "font.sans-serif": FONT_STACK,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.edgecolor": BASELINE,
            "axes.labelcolor": INK_SECONDARY,
            "axes.titlecolor": INK_PRIMARY,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "xtick.color": INK_MUTED,
            "ytick.color": INK_MUTED,
            "xtick.labelcolor": INK_SECONDARY,
            "ytick.labelcolor": INK_SECONDARY,
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "lines.linewidth": 2.0,
            "lines.solid_capstyle": "round",
            "legend.frameon": False,
            "svg.fonttype": "none",  # keep text as real text in SVGs
        }
    )


apply_rcparams()


# ---------------------------------------------------------------------------
# Figure frame: banners, title block, footer
# ---------------------------------------------------------------------------

# Vertical layout of the figure, in figure-fraction units (0 = bottom, 1 = top).
BANNER_H = 0.045
TITLE_Y = 0.895
SUBTITLE_Y = 0.845
PLOT_TOP = 0.765
PLOT_BOTTOM = 0.17
FOOTER_Y = 0.075


def plain(text: str) -> str:
    """Escape ``$`` so matplotlib draws spec text literally instead of as math."""
    return text.replace("$", r"\$")


def new_figure(style: IntsumStyle = DEFAULT_STYLE) -> tuple[Figure, Axes]:
    """Blank figure with the plot area positioned inside the INTSUM frame."""
    fig = plt.figure(figsize=(style.width_in, style.height_in), dpi=style.dpi)
    ax = fig.add_axes((0.075, PLOT_BOTTOM, 0.85, PLOT_TOP - PLOT_BOTTOM))
    return fig, ax


def frame_figure(
    fig: Figure,
    *,
    title: str,
    subtitle: str | None,
    source: str,
    as_of: datetime | None = None,
    style: IntsumStyle = DEFAULT_STYLE,
) -> Figure:
    """Add classification banners, title block, and sourcing footer."""
    f = style.fonts
    bg, fg = BANNER_BG, BANNER_FG

    # Top and bottom classification banners
    for y in (1 - BANNER_H, 0):
        fig.patches.append(
            Rectangle(
                (0, y),
                1,
                BANNER_H,
                transform=fig.transFigure,
                color=bg,
                zorder=10,
            )
        )
        fig.text(
            0.5,
            y + BANNER_H / 2,
            CLASSIFICATION,
            ha="center",
            va="center",
            color=fg,
            fontsize=f["banner"],
            fontweight="bold",
            zorder=11,
        )

    # Title block, left aligned with the plot
    fig.text(
        0.075,
        TITLE_Y,
        plain(title),
        ha="left",
        va="center",
        fontsize=f["title"],
        fontweight="bold",
        color=INK_PRIMARY,
    )
    if subtitle:
        fig.text(
            0.075,
            SUBTITLE_Y,
            plain(subtitle),
            ha="left",
            va="center",
            fontsize=f["subtitle"],
            color=INK_SECONDARY,
        )

    # Footer: source on the left, product line and timestamp on the right
    left = f"Source: {plain(source)}"
    if style.extra_footer:
        left += f"   |   {style.extra_footer}"
    fig.text(0.075, FOOTER_Y, left, ha="left", va="center", fontsize=f["footer"], color=INK_MUTED)

    right = style.product_line
    if style.show_generated_stamp:
        stamp = (as_of or datetime.now(UTC)).strftime("%d %b %Y %H%MZ").upper()
        right += f"   |   As of {stamp}"
    fig.text(0.925, FOOTER_Y, right, ha="right", va="center", fontsize=f["footer"], color=INK_MUTED)
    return fig
