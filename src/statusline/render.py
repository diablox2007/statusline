"""ANSI output renderer: quota section."""

from __future__ import annotations

import sys

from .quota import QuotaData, calc_remaining

RST = "\033[0m"


def _fg(code: int) -> str:
    return f"\033[38;5;{code}m"


C_LABEL = _fg(250)
C_DIM = _fg(243)
C_PCT = _fg(248)
C_MONEY = _fg(144)
C_BAR_FILL = _fg(66)
C_BAR_BG = _fg(238)
C_SEP = _fg(238)

BAR_WIDTH = 10

# Cursor control
CLEAR_LINE = "\033[K"
CURSOR_UP = "\033[{}A"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


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


def render_quota(quota: QuotaData, rewind: int = 0) -> int:
    """Render quota section. Returns number of lines written.

    If rewind > 0, moves cursor up that many lines first (for in-place refresh).
    """
    if rewind > 0:
        _w(CURSOR_UP.format(rewind))

    lines = 0

    if not quota or not quota.entries:
        sys.stdout.flush()
        return lines

    # Recompute remaining from reset_at for each entry
    entries = []
    for e in quota.entries:
        remaining = calc_remaining(e.reset_at) if e.reset_at else e.remaining
        entries.append((e, remaining))

    # Separator
    _w(f"{CLEAR_LINE}{C_SEP}" + "\u2500" * 60 + f"{RST}\n")
    lines += 1

    # Column widths
    max_label = max(len(e.label) for e, _ in entries)

    mid_texts: list[str] = []
    for e, _ in entries:
        parts = ""
        if e.spent > 0 or e.limit > 0:
            parts += f"${e.spent:.2f}/${e.limit:.2f} "
        if e.reset_label:
            parts += f"Resets {e.reset_label}"
        mid_texts.append(parts)
    max_mid = max((len(m) for m in mid_texts), default=0)

    # Compute max remaining width for right-padding (avoid trailing jitter)
    max_rem = max((len(r) for _, r in entries if r), default=0)

    for (entry, remaining), mid_text in zip(entries, mid_texts):
        _w(CLEAR_LINE)

        # Label
        pad_l = max_label + 1 - len(entry.label)
        _w(f"{C_LABEL}{entry.label}{RST}{' ' * pad_l}")

        # Bar
        _w(_bar(entry.pct))

        # Percentage
        pct_s = f"{entry.pct:g}%"
        pad_p = 4 - len(pct_s)
        _w(f" {C_PCT}{pct_s}{RST}{' ' * pad_p}")

        # Spent + Reset (padded)
        colored_mid = ""
        if entry.spent > 0 or entry.limit > 0:
            colored_mid += f"{C_MONEY}${entry.spent:.2f}{C_DIM}/{RST}{C_MONEY}${entry.limit:.2f}{RST} "
        if entry.reset_label:
            colored_mid += f"{C_DIM}Resets {entry.reset_label}{RST}"
        pad_m = max_mid + 1 - len(mid_text)
        _w(f"{colored_mid}{' ' * pad_m}")

        # [remaining] (padded to max width to avoid flicker)
        if remaining:
            pad_r = max_rem - len(remaining)
            _w(f"{C_DIM}[{RST}{C_PCT}{remaining}{RST}{' ' * pad_r}{C_DIM}]{RST}")

        _w("\n")
        lines += 1

    sys.stdout.flush()
    return lines
