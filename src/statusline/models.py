"""Data models for statusline quota tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class QuotaEntry:
    label: str           # e.g. "Current session"
    pct: float           # 0–100
    reset_label: str     # e.g. "9pm" or "Feb 19 at 4am"
    timezone: str = ""   # e.g. "Asia/Bangkok"
    spent: float = 0.0   # only for extra usage
    limit: float = 0.0   # only for extra usage
    used: int = 0        # token-based usage (e.g. session output tokens)
    total: int = 0       # token-based limit
    reset_at: str = ""   # ISO 8601 timestamp for remaining calc
    remaining: str = ""  # computed dynamically


@dataclass
class QuotaData:
    entries: list[QuotaEntry] = field(default_factory=list)


@dataclass
class TokenCounts:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return (self.input_tokens + self.output_tokens
                + self.cache_creation_tokens + self.cache_read_tokens)


@dataclass
class UsageEntry:
    """Individual usage record extracted from a JSONL line."""
    timestamp: datetime
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    message_id: str = ""
    request_id: str = ""


@dataclass
class SessionBlock:
    """Aggregated 5-hour session block."""
    id: str = ""
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    entries: list[UsageEntry] = field(default_factory=list)
    token_counts: TokenCounts = field(default_factory=TokenCounts)
    is_active: bool = False
    is_gap: bool = False
    actual_end_time: datetime | None = None
    per_model_stats: dict[str, dict] = field(default_factory=dict)
    models: list[str] = field(default_factory=list)
    sent_messages_count: int = 0
    cost_usd: float = 0.0
    limit_messages: list[dict] = field(default_factory=list)


def model_family(model: str) -> str:
    """Map a model id to its family name (opus/sonnet/haiku/other)."""
    m = model.lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return "other"


def calc_remaining(reset_at: str) -> str:
    """Compute remaining time string from an ISO 8601 timestamp.

    Returns e.g. "4h21m", "37m", or "" if past/unparseable.
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
        if days > 0:
            return f"{days}d{hours}h"
        if hours > 0:
            return f"{hours}h{mins:02d}m"
        return f"{mins}m"
    except (ValueError, TypeError):
        return ""
