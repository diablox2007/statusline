"""ANSI output renderer: quota section."""

from __future__ import annotations

import sys

from .models import QuotaData, calc_remaining

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


def _fmt_tokens(n: int) -> str:
    """Format token count: 785 → '785', 8785 → '8.8k', 88000 → '88k', 1000000 → '1M'."""
    if n < 1000:
        return str(n)
    if n >= 1_000_000:
        m = n / 1_000_000
        return f"{m:.0f}M" if m == int(m) else f"{m:.1f}M"
    k = n / 1000
    return f"{k:.0f}k" if k == int(k) else f"{k:.1f}k"


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

    # Value texts: tokens "40.2k/88k" or money "$22.73/$50.00"
    val_texts: list[str] = []
    for e, _ in entries:
        if e.used > 0 or e.total > 0:
            val_texts.append(f"{_fmt_tokens(e.used)}/{_fmt_tokens(e.total)}")
        elif e.spent > 0 or e.limit > 0:
            val_texts.append(f"${e.spent:.2f}/${e.limit:.2f}")
        else:
            val_texts.append("")
    max_val = max((len(v) for v in val_texts), default=0)

    pct_texts = [f"({e.pct:g}%)" for e, _ in entries]
    max_pct = max(len(p) for p in pct_texts)

    tail_texts: list[str] = []
    for e, _ in entries:
        parts = ""
        if e.reset_label:
            parts += f"Resets {e.reset_label}"
        tail_texts.append(parts)
    max_tail = max((len(t) for t in tail_texts), default=0)

    # Compute max remaining width for right-padding (avoid trailing jitter)
    max_rem = max((len(r) for _, r in entries if r), default=0)

    for (entry, remaining), val_text, pct_text, tail_text in zip(
        entries, val_texts, pct_texts, tail_texts,
    ):
        _w(CLEAR_LINE)

        # Label
        pad_l = max_label + 1 - len(entry.label)
        _w(f"{C_LABEL}{entry.label}{RST}{' ' * pad_l}")

        # Bar
        _w(_bar(entry.pct))

        # Value: tokens or money (right after bar)
        if val_text:
            pad_v = max_val - len(val_text)
            if entry.used > 0 or entry.total > 0:
                _w(f" {C_PCT}{_fmt_tokens(entry.used)}{C_DIM}/{RST}{C_PCT}{_fmt_tokens(entry.total)}{RST}{' ' * pad_v}")
            else:
                _w(f" {C_MONEY}${entry.spent:.2f}{C_DIM}/{RST}{C_MONEY}${entry.limit:.2f}{RST}{' ' * pad_v}")
        elif max_val > 0:
            _w(" " * (max_val + 1))

        # Percentage in dim parens
        pad_p = max_pct - len(pct_text)
        _w(f" {C_DIM}({RST}{C_PCT}{entry.pct:g}%{RST}{C_DIM}){RST}{' ' * pad_p} ")

        # Reset (padded)
        colored_tail = ""
        if entry.reset_label:
            colored_tail += f"{C_DIM}Resets {entry.reset_label}{RST}"
        pad_t = max_tail + 1 - len(tail_text)
        _w(f"{colored_tail}{' ' * pad_t}")

        # [remaining] (padded to max width to avoid flicker)
        if remaining:
            pad_r = max_rem - len(remaining)
            _w(f"{C_DIM}[{RST}{C_PCT}{remaining}{RST}{' ' * pad_r}{C_DIM}]{RST}")

        _w("\n")
        lines += 1

    sys.stdout.flush()
    return lines
