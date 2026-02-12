"""ANSI output renderer: quota section."""

from __future__ import annotations

import sys

from .quota import QuotaData

RST = "\033[0m"


def _fg(code: int) -> str:
    return f"\033[38;5;{code}m"


C_LABEL = _fg(250)
C_DIM = _fg(243)
C_PCT = _fg(248)
C_MONEY = _fg(144)
C_BAR_FILL = _fg(66)
C_BAR_BG = _fg(238)

BAR_WIDTH = 10


def _w(s: str) -> None:
    sys.stdout.write(s)


def _bar(pct: float) -> str:
    p = max(0.0, min(pct, 100.0))
    filled = round(p * BAR_WIDTH / 100.0)
    empty = BAR_WIDTH - filled
    return (
        f"{C_BAR_FILL}" + "\u25aa" * filled
        + f"{C_BAR_BG}" + "\u25ab" * empty
        + RST
    )


def render_quota(quota: QuotaData) -> None:
    if not quota or not quota.entries:
        return

    # Header: "Usage (Asia/Bangkok)"
    tz = next((e.timezone for e in quota.entries if e.timezone), "")
    tz_part = f" ({tz})" if tz else ""
    _w(f"\n{C_DIM}Usage{tz_part}{RST}\n")

    # Column widths (visible chars only)
    max_label = max(len(e.label) for e in quota.entries)

    # Build middle column (spent + reset) plain text per entry
    mid_texts: list[str] = []
    for e in quota.entries:
        parts = ""
        if e.spent > 0 or e.limit > 0:
            parts += f"${e.spent:.2f}/${e.limit:.2f} "
        if e.reset_label:
            parts += f"Resets {e.reset_label}"
        mid_texts.append(parts)
    max_mid = max((len(m) for m in mid_texts), default=0)

    for entry, mid_text in zip(quota.entries, mid_texts):
        # Label (padded)
        pad_l = max_label + 1 - len(entry.label)
        _w(f"{C_LABEL}{entry.label}{RST}{' ' * pad_l}")

        # Bar
        _w(_bar(entry.pct))

        # Percentage (padded to 4 visible chars)
        pct_s = f"{entry.pct:g}%"
        pad_p = 4 - len(pct_s)
        _w(f" {C_PCT}{pct_s}{RST}{' ' * pad_p}")

        # Middle column: spent + reset (padded as one unit)
        colored_mid = ""
        if entry.spent > 0 or entry.limit > 0:
            colored_mid += f"{C_MONEY}${entry.spent:.2f}{C_DIM}/{RST}{C_MONEY}${entry.limit:.2f}{RST} "
        if entry.reset_label:
            colored_mid += f"{C_DIM}Resets {entry.reset_label}{RST}"
        pad_m = max_mid + 1 - len(mid_text)
        _w(f"{colored_mid}{' ' * pad_m}")

        # [remaining]
        if entry.remaining:
            _w(f"{C_DIM}[{RST}{C_PCT}{entry.remaining}{RST}{C_DIM}]{RST}")

        _w("\n")

    sys.stdout.flush()
