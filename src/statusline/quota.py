"""Quota/rate-limit reader: loads data from a JSON cache file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_QUOTA_PATH = Path("/tmp/claude_quota.json")


@dataclass(frozen=True)
class QuotaEntry:
    label: str           # e.g. "Current session"
    pct: float           # 0–100
    reset_label: str     # e.g. "9pm" or "Feb 19 at 4am"
    timezone: str = ""   # e.g. "Asia/Bangkok"
    spent: float = 0.0   # only for extra usage
    limit: float = 0.0   # only for extra usage
    reset_at: str = ""   # ISO 8601 timestamp for remaining calc
    remaining: str = ""  # computed dynamically


@dataclass
class QuotaData:
    entries: list[QuotaEntry] = field(default_factory=list)


def calc_remaining(reset_at: str) -> str:
    """Compute remaining time string from an ISO 8601 timestamp.

    Returns e.g. "4h21m03s", "37m12s", "2d3h", or "" if past/unparseable.
    """
    try:
        target = datetime.fromisoformat(reset_at)
        now = datetime.now(timezone.utc)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        total_sec = int((target - now).total_seconds())
        if total_sec <= 0:
            return ""
        days = total_sec // 86400
        hours = (total_sec % 86400) // 3600
        mins = (total_sec % 3600) // 60
        secs = total_sec % 60
        if days > 0:
            return f"{days}d{hours}h"
        if hours > 0:
            return f"{hours}h{mins:02d}m"
        return f"{mins}m"
    except (ValueError, TypeError):
        return ""


def get_quota_path() -> Path:
    path_str = os.environ.get("CLAUDE_QUOTA_FILE", "")
    return Path(path_str) if path_str else DEFAULT_QUOTA_PATH


def read_quota() -> QuotaData:
    """Read quota data from the cache file.

    Expected JSON format:
    [
      {
        "label": "Current session",
        "pct": 32,
        "reset": "9pm",
        "tz": "Asia/Bangkok",
        "reset_at": "2026-02-12T21:00:00+07:00"
      },
      ...
    ]
    """
    path = get_quota_path()

    if not path.is_file():
        return QuotaData()

    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return QuotaData()

    entries: list[QuotaEntry] = []
    items = raw if isinstance(raw, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue

        reset_at = str(item.get("reset_at", ""))

        entries.append(QuotaEntry(
            label=str(item.get("label", "")),
            pct=float(item.get("pct", 0)),
            reset_label=str(item.get("reset", "")),
            timezone=str(item.get("tz", "")),
            spent=float(item.get("spent", 0)),
            limit=float(item.get("limit", 0)),
            reset_at=reset_at,
            remaining=calc_remaining(reset_at),
        ))

    return QuotaData(entries=entries)
