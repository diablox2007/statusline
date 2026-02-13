"""JSONL reader: discover files, parse lines, extract tokens.

Primary entry point:
  - load_usage_entries()    → scan ALL JSONL files (claude-monitor approach)
  - read_hook_json()        → read the hook JSON (only used by __main__.py live mode)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import HOOK_JSON, MODEL_PRICING, PROJECTS_DIR, build_candidate_paths
from ..models import TokenCounts, UsageEntry


# ---------------------------------------------------------------------------
# Hook JSON (still needed by run.sh / Line 1)
# ---------------------------------------------------------------------------

def read_hook_json() -> dict:
    """Read the hook JSON dumped by run.sh."""
    try:
        return json.loads(Path(HOOK_JSON).read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def read_transcript_output_tokens(
    transcript_path: str,
    since: datetime | None = None,
) -> int:
    """Sum output tokens from a session transcript JSONL.

    Claude Code writes multiple streaming events per API request, each
    carrying a cumulative ``message.usage.output_tokens``.  We keep the
    **last** entry per unique (message_id, request_id) pair so we get
    the final cumulative value rather than an early partial.

    Args:
        transcript_path: Path to the session's ``.jsonl`` file.
        since: If given, only count entries with timestamp >= this value.

    Returns:
        Total output tokens (sum of last-entry-per-request).
    """
    try:
        fpath = Path(transcript_path)
        if not fpath.is_file():
            return 0
    except (TypeError, OSError):
        return 0

    # Keep last-seen output_tokens per request
    last_out: dict[str, int] = {}

    try:
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if data.get("type") != "assistant":
                    continue

                # Timestamp filter
                if since is not None:
                    ts = _parse_timestamp(data.get("timestamp"))
                    if not ts or ts < since:
                        continue

                # Extract output_tokens from message.usage
                msg = data.get("message", {})
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage", {})
                if not isinstance(usage, dict):
                    continue
                out = usage.get("output_tokens", 0)
                if out <= 0:
                    continue

                # Dedup key: keep last (largest cumulative) per request
                msg_id = msg.get("id", "")
                req_id = data.get("requestId") or data.get("request_id", "")
                if msg_id and req_id:
                    key = f"{msg_id}:{req_id}"
                    last_out[key] = out  # always overwrite → keeps last
                else:
                    # No dedup key — count each entry individually
                    last_out[id(data)] = out
    except OSError:
        return 0

    return sum(last_out.values())


def _get_first(d: dict, *keys: str) -> int:
    """Return the value of the first key found in *d*, or 0."""
    for k in keys:
        if k in d:
            return d[k]
    return 0


def extract_tokens(usage: dict) -> TokenCounts:
    """Extract token counts from a message.usage dict."""
    return TokenCounts(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_creation_tokens=_get_first(
            usage, "cache_creation_input_tokens", "cache_creation_tokens",
        ),
        cache_read_tokens=_get_first(
            usage, "cache_read_input_tokens", "cache_read_tokens",
        ),
    )


# ---------------------------------------------------------------------------
# Full JSONL scanning (reference project approach)
# ---------------------------------------------------------------------------

def _find_jsonl_files(projects_dir: str | None = None) -> list[Path]:
    """Find all .jsonl files across candidate data directories.

    If *projects_dir* is given, only that single directory is scanned.
    Otherwise, :func:`build_candidate_paths` discovers all valid dirs.
    """
    if projects_dir is not None:
        root = Path(projects_dir).expanduser()
        return list(root.rglob("*.jsonl")) if root.is_dir() else []

    candidates = build_candidate_paths()
    if not candidates:
        root = Path(PROJECTS_DIR).expanduser()
        return list(root.rglob("*.jsonl")) if root.is_dir() else []

    all_files: list[Path] = []
    seen: set[Path] = set()
    for d in candidates:
        for f in d.rglob("*.jsonl"):
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                all_files.append(f)
    return all_files


def _parse_timestamp(value: str | int | float | None) -> datetime | None:
    """Parse timestamp from ISO string or unix epoch to UTC datetime."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
    except (ValueError, OSError):
        pass
    return None


def _extract_entry_tokens(data: dict) -> dict[str, int]:
    """Extract token counts from a JSONL entry (multi-source lookup).

    For assistant entries: checks message.usage → usage → data itself.
    For other types: checks usage → message.usage → data itself.
    Takes the first source that has non-zero input or output tokens.
    """
    tokens = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
    }

    is_assistant = data.get("type") == "assistant"
    sources: list[dict] = []

    if is_assistant:
        msg = data.get("message", {})
        if isinstance(msg, dict) and "usage" in msg:
            sources.append(msg["usage"])
        if "usage" in data:
            sources.append(data["usage"])
        sources.append(data)
    else:
        if "usage" in data:
            sources.append(data["usage"])
        msg = data.get("message", {})
        if isinstance(msg, dict) and "usage" in msg:
            sources.append(msg["usage"])
        sources.append(data)

    for src in sources:
        if not isinstance(src, dict):
            continue
        inp = _get_first(src, "input_tokens", "inputTokens")
        out = _get_first(src, "output_tokens", "outputTokens")
        cc = _get_first(src, "cache_creation_tokens", "cache_creation_input_tokens")
        cr = _get_first(src, "cache_read_input_tokens", "cache_read_tokens")
        if inp > 0 or out > 0:
            tokens["input_tokens"] = int(inp)
            tokens["output_tokens"] = int(out)
            tokens["cache_creation_tokens"] = int(cc)
            tokens["cache_read_tokens"] = int(cr)
            break

    return tokens


def _estimate_cost(tok: dict[str, int]) -> float:
    """Estimate cost (USD) using flat Sonnet pricing (no cache_read).

    Empirical testing shows Claude Code's extra-usage billing closely
    matches flat Sonnet rates ($3/$15/$3.75 per M tokens) regardless of
    the actual model used. Per-model API pricing (MODEL_PRICING) would
    overcharge Opus entries by ~37%.
    """
    pricing = MODEL_PRICING["sonnet"]
    return (
        tok["input_tokens"] * pricing["input"]
        + tok["output_tokens"] * pricing["output"]
        + tok["cache_creation_tokens"] * pricing["cache_creation"]
    ) / 1_000_000


def _extract_model(data: dict) -> str:
    """Extract model name from various data fields."""
    candidates = [
        data.get("message", {}).get("model")
        if isinstance(data.get("message"), dict) else None,
        data.get("model"),
        data.get("usage", {}).get("model")
        if isinstance(data.get("usage"), dict) else None,
    ]
    for c in candidates:
        if c and isinstance(c, str):
            return c
    return ""


def _create_unique_hash(data: dict) -> str | None:
    """Create dedup hash: message_id:request_id."""
    msg = data.get("message", {})
    message_id = data.get("message_id") or (
        msg.get("id") if isinstance(msg, dict) else None
    )
    request_id = data.get("requestId") or data.get("request_id")
    if message_id and request_id:
        return f"{message_id}:{request_id}"
    return None


def load_usage_entries(
    hours_back: int | None = 96,
    projects_dir: str | None = None,
    include_raw: bool = False,
) -> tuple[list[UsageEntry], list[dict] | None]:
    """Scan all JSONL files, deduplicate, return UsageEntry objects.

    Args:
        hours_back: Only include entries from last N hours (None = all).
        projects_dir: Override ~/.claude/projects path.
        include_raw: If True, also return raw dicts (for limit detection).

    Returns:
        (sorted_entries, raw_entries_or_None)
    """
    cutoff = None
    if hours_back is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    files = _find_jsonl_files(projects_dir)
    entries: list[UsageEntry] = []
    raw_entries: list[dict] | None = [] if include_raw else None
    seen: set[str] = set()

    for fpath in files:
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Keep raw entries (before filtering) for limit detection
                    if include_raw and raw_entries is not None:
                        raw_entries.append(data)

                    # Deduplicate
                    h = _create_unique_hash(data)
                    if h:
                        if h in seen:
                            continue
                        seen.add(h)

                    # Parse timestamp
                    ts = _parse_timestamp(data.get("timestamp"))
                    if not ts:
                        continue
                    if cutoff and ts < cutoff:
                        continue

                    # Extract tokens — skip entries with no usage data
                    tok = _extract_entry_tokens(data)
                    if tok["input_tokens"] == 0 and tok["output_tokens"] == 0:
                        continue

                    # Extract cost — prefer explicit field, else estimate
                    model = _extract_model(data)
                    cost = 0.0
                    raw_cost = data.get("cost") or data.get("cost_usd")
                    if isinstance(raw_cost, (int, float)):
                        cost = float(raw_cost)
                    if cost == 0.0 and (tok["input_tokens"] > 0
                                        or tok["output_tokens"] > 0):
                        cost = _estimate_cost(tok)

                    # Build entry
                    msg = data.get("message", {})
                    entries.append(UsageEntry(
                        timestamp=ts,
                        input_tokens=tok["input_tokens"],
                        output_tokens=tok["output_tokens"],
                        cache_creation_tokens=tok["cache_creation_tokens"],
                        cache_read_tokens=tok["cache_read_tokens"],
                        cost_usd=cost,
                        model=model,
                        message_id=data.get("message_id") or (
                            msg.get("id", "") if isinstance(msg, dict) else ""
                        ),
                        request_id=(
                            data.get("requestId")
                            or data.get("request_id")
                            or ""
                        ),
                    ))
        except OSError:
            continue

    entries.sort(key=lambda e: e.timestamp)
    return entries, raw_entries
