"""Session analyzer: build QuotaEntry list from JSONL data.

Pipeline (fully JSONL-based, no hook JSON dependency):
  1. load_usage_entries()                 → scan candidate data directories
  2. SessionAnalyzer.transform_to_blocks() → 5h session windows (with gaps)
  3. compute_p90_cost_limit()             → dynamic limit (fallback: plan limit)
  4. detect_limits()                      → rate-limit messages from raw JSONL
  5. Aggregate entries for session/weekly/monthly views
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import (
    EXTRA_USAGE_LIMIT,
    WEEKLY_OUTPUT_LIMIT,
    WEEKLY_SONNET_LIMIT,
    get_plan_limits,
)
from ..data.aggregator import SessionAnalyzer
from ..data.reader import load_usage_entries, read_hook_json, read_transcript_output_tokens
from ..models import QuotaData, QuotaEntry, calc_remaining, model_family


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _format_reset_label(dt: datetime) -> str:
    """Human-readable reset time, e.g. '9pm', '11:30pm', 'Feb 19 at 4am'."""
    local = dt.astimezone()
    now = datetime.now().astimezone()

    hour12 = local.hour % 12 or 12
    ampm = "am" if local.hour < 12 else "pm"
    if local.minute == 0:
        time_str = f"{hour12}{ampm}"
    else:
        time_str = f"{hour12}:{local.minute:02d}{ampm}"

    if local.date() == now.date():
        return time_str
    if local.date() == (now + timedelta(days=1)).date():
        return f"tmrw {time_str}"
    month = local.strftime("%b")
    return f"{month} {local.day} at {time_str}"


def _last_weekly_reset() -> datetime:
    """Last Monday 04:00 local — start of the current weekly window."""
    now = datetime.now().astimezone()
    days_since_monday = now.weekday()          # Mon=0
    if days_since_monday == 0 and now.hour < 4:
        days_since_monday = 7
    target = now.replace(hour=4, minute=0, second=0, microsecond=0)
    target -= timedelta(days=days_since_monday)
    return target


def _next_weekly_reset() -> datetime:
    """Next Monday 04:00 local — end of the current weekly window."""
    now = datetime.now().astimezone()
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0 and now.hour >= 4:
        days_until_monday = 7
    target = now.replace(hour=4, minute=0, second=0, microsecond=0)
    target += timedelta(days=days_until_monday)
    return target


def _next_month_start() -> datetime:
    """First day of next month, midnight local."""
    now = datetime.now().astimezone()
    if now.month == 12:
        return now.replace(year=now.year + 1, month=1, day=1,
                           hour=0, minute=0, second=0, microsecond=0)
    return now.replace(month=now.month + 1, day=1,
                       hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def compute_quota() -> QuotaData:
    """Compute all quota entries by scanning JSONL files.

    Produces 4 entries:
      1. Current session  — output tokens vs plan output limit
      2. Current week     — all-model output tokens vs weekly limit
      3. Week (Sonnet)    — Sonnet output tokens vs Sonnet weekly limit
      4. Extra usage      — monthly cost vs spending cap

    Data source: ~/.claude/projects/**/*.jsonl + current session
    transcript for accurate per-request output token accounting.
    """
    entries, raw_entries = load_usage_entries(hours_back=96, include_raw=True)
    if not entries:
        return QuotaData()

    # ── Build session blocks ───────────────────────────────────────
    sa = SessionAnalyzer(session_duration_hours=5)
    blocks = sa.transform_to_blocks(entries)

    # Detect limit messages and attach to blocks
    if raw_entries:
        limit_infos = sa.detect_limits(raw_entries)
        for block in blocks:
            block.limit_messages = [
                li for li in limit_infos
                if block.start_time <= li["timestamp"] <= block.end_time
            ]

    # ── Find active block ─────────────────────────────────────────
    active = None
    for b in reversed(blocks):
        if b.is_active and not b.is_gap:
            active = b
            break

    result_entries: list[QuotaEntry] = []

    # ── 1. Current session (output-token-based) ──────────────────
    #
    # Claude Code's /usage "Current session" tracks output_tokens
    # against the plan's per-window output limit.  We read the
    # current transcript directly (keeping the *last* streaming
    # entry per request) rather than using load_usage_entries()
    # which deduplicates across files and loses cumulative values.
    plan_limits = get_plan_limits()
    output_limit = plan_limits["output_limit"]

    hook = read_hook_json()
    transcript_path = hook.get("transcript_path", "")

    session_output = 0
    if transcript_path and active:
        session_output = read_transcript_output_tokens(
            transcript_path, since=active.start_time,
        )
    elif transcript_path:
        session_output = read_transcript_output_tokens(transcript_path)

    session_pct = (
        session_output / output_limit * 100 if output_limit > 0 else 0.0
    )

    if active:
        reset_dt = active.end_time
        for li in active.limit_messages:
            if li.get("reset_time"):
                reset_dt = li["reset_time"]
                break

        result_entries.append(QuotaEntry(
            label="Session",
            pct=round(session_pct, 1),
            used=session_output,
            total=output_limit,
            reset_label=_format_reset_label(reset_dt),
            reset_at=reset_dt.isoformat(),
            remaining=calc_remaining(reset_dt.isoformat()),
        ))
    else:
        result_entries.append(QuotaEntry(
            label="Session",
            pct=round(session_pct, 1),
            used=session_output,
            total=output_limit,
            reset_label="",
        ))

    # ── Weekly aggregation ────────────────────────────────────────
    week_start = _last_weekly_reset().astimezone(timezone.utc)
    weekly_all = 0
    weekly_sonnet = 0
    for e in entries:
        if e.timestamp >= week_start:
            weekly_all += e.output_tokens
            if model_family(e.model) == "sonnet":
                weekly_sonnet += e.output_tokens

    weekly_reset = _next_weekly_reset()
    weekly_reset_label = _format_reset_label(weekly_reset)
    weekly_reset_at = weekly_reset.isoformat()

    # ── 2. Current week (all models) ──────────────────────────────
    all_pct = (weekly_all / WEEKLY_OUTPUT_LIMIT * 100) if WEEKLY_OUTPUT_LIMIT > 0 else 0.0
    result_entries.append(QuotaEntry(
        label="Current week",
        pct=round(all_pct, 1),
        used=weekly_all,
        total=WEEKLY_OUTPUT_LIMIT,
        reset_label=weekly_reset_label,
        reset_at=weekly_reset_at,
        remaining=calc_remaining(weekly_reset_at),
    ))

    # ── 3. Current week (Sonnet only) ─────────────────────────────
    sonnet_pct = (weekly_sonnet / WEEKLY_SONNET_LIMIT * 100) if WEEKLY_SONNET_LIMIT > 0 else 0.0
    result_entries.append(QuotaEntry(
        label="Week (Sonnet)",
        pct=round(sonnet_pct, 1),
        used=weekly_sonnet,
        total=WEEKLY_SONNET_LIMIT,
        reset_label=weekly_reset_label,
        reset_at=weekly_reset_at,
        remaining=calc_remaining(weekly_reset_at),
    ))

    # ── 4. Extra usage (monthly cost) ─────────────────────────────
    month_start_dt = datetime.now().astimezone().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    ).astimezone(timezone.utc)

    # Prefer hook JSON cost for current session accuracy
    monthly_cost = sum(
        e.cost_usd for e in entries
        if e.timestamp >= month_start_dt and e.cost_usd
    )

    extra_pct = (monthly_cost / EXTRA_USAGE_LIMIT * 100) if EXTRA_USAGE_LIMIT > 0 else 0.0
    monthly_reset = _next_month_start()
    monthly_reset_label = _format_reset_label(monthly_reset)
    monthly_reset_at = monthly_reset.isoformat()

    result_entries.append(QuotaEntry(
        label="Extra usage",
        pct=round(extra_pct, 1),
        reset_label=monthly_reset_label,
        spent=round(monthly_cost, 2),
        limit=EXTRA_USAGE_LIMIT,
        reset_at=monthly_reset_at,
        remaining=calc_remaining(monthly_reset_at),
    ))

    return QuotaData(entries=result_entries)
