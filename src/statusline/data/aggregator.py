"""Session analyzer: create 5-hour blocks and detect rate limits.

Follows the reference project (Claude-Code-Usage-Monitor) approach:
  1. Sort all UsageEntry objects by timestamp
  2. Group into 5-hour session blocks (rounded to hour boundary)
  3. Mark blocks as active if end_time > now
  4. Detect rate-limit messages from raw JSONL entries
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..config import COMMON_TOKEN_LIMITS, P90_LIMIT_THRESHOLD, P90_MIN_SESSIONS
from ..models import SessionBlock, TokenCounts, UsageEntry, model_family
from .reader import _parse_timestamp


class SessionAnalyzer:
    """Creates session blocks and detects limits from JSONL data."""

    def __init__(self, session_duration_hours: int = 5):
        self.session_duration = timedelta(hours=session_duration_hours)

    # ── Public API ──────────────────────────────────────────────────

    def transform_to_blocks(self, entries: list[UsageEntry]) -> list[SessionBlock]:
        """Group usage entries into 5-hour session blocks.

        Inserts gap blocks (is_gap=True) between active sessions when
        inactivity exceeds the session duration, matching claude-monitor.
        """
        if not entries:
            return []

        blocks: list[SessionBlock] = []
        current: SessionBlock | None = None

        for entry in entries:
            if current is None or self._should_create_new_block(current, entry):
                if current:
                    self._finalize(current)
                    blocks.append(current)
                    gap = self._check_for_gap(current, entry)
                    if gap:
                        blocks.append(gap)
                current = self._new_block(entry)
            self._add_entry(current, entry)

        if current:
            self._finalize(current)
            blocks.append(current)

        self._mark_active(blocks)
        return blocks

    def detect_limits(self, raw_entries: list[dict]) -> list[dict]:
        """Scan raw JSONL entries for rate-limit / token-limit messages.

        Checks two types:
          - system messages containing "limit" or "rate"
          - user messages with tool_result containing "limit reached"
        """
        limits: list[dict] = []
        for raw in raw_entries:
            info = self._detect_single(raw)
            if info:
                limits.append(info)
        return limits

    def compute_p90_output_limit(
        self,
        blocks: list[SessionBlock],
        min_limit: int = 19_000,
    ) -> int | None:
        """Compute P90 output-token limit from completed session blocks.

        Returns the P90 value (or *None* when fewer than P90_MIN_SESSIONS
        completed blocks exist).  Prefers blocks that "hit" a known plan
        limit; if none did, falls back to ALL completed blocks (matching
        claude-monitor's approach instead of returning None immediately).
        """
        completed = [
            b for b in blocks if not b.is_gap and not b.is_active
        ]
        if len(completed) < P90_MIN_SESSIONS:
            return None

        def _hit_limit(output_tokens: int) -> bool:
            return any(
                output_tokens >= lim * P90_LIMIT_THRESHOLD
                for lim in COMMON_TOKEN_LIMITS
            )

        hit_tokens = [
            b.token_counts.output_tokens
            for b in completed
            if _hit_limit(b.token_counts.output_tokens)
        ]

        # Prefer hit blocks; fall back to all completed blocks
        if hit_tokens:
            values = hit_tokens
        else:
            values = [
                b.token_counts.output_tokens
                for b in completed
                if b.token_counts.output_tokens > 0
            ]
        if not values:
            return min_limit

        return self._linear_interpolation_p90(values, min_limit)

    def compute_p90_cost_limit(
        self,
        blocks: list[SessionBlock],
        min_limit: float = 18.0,
        buffer: float = 1.2,
    ) -> float | None:
        """Compute P90 cost limit from completed session blocks.

        Returns the P90 cost × *buffer* (or *None* when fewer than
        P90_MIN_SESSIONS completed blocks exist).  Uses the same
        linear-interpolation approach as compute_p90_output_limit.
        """
        completed = [
            b for b in blocks if not b.is_gap and not b.is_active
        ]
        if len(completed) < P90_MIN_SESSIONS:
            return None

        costs = sorted(b.cost_usd for b in completed if b.cost_usd > 0)
        if not costs:
            return None

        p90 = self._linear_interpolation_p90_float(costs)
        return max(p90 * buffer, min_limit)

    # ── P90 math ─────────────────────────────────────────────────

    @staticmethod
    def _linear_interpolation_p90(values: list[int], min_val: int) -> int:
        """Compute P90 from int values using linear interpolation."""
        vs = sorted(values)
        n = len(vs)
        rank = 0.9 * (n - 1)
        lower = int(rank)
        upper = min(lower + 1, n - 1)
        frac = rank - lower
        p90 = vs[lower] + frac * (vs[upper] - vs[lower])
        return max(int(p90), min_val)

    @staticmethod
    def _linear_interpolation_p90_float(values: list[float]) -> float:
        """Compute P90 from float values using linear interpolation."""
        vs = sorted(values)
        n = len(vs)
        rank = 0.9 * (n - 1)
        lower = int(rank)
        upper = min(lower + 1, n - 1)
        frac = rank - lower
        return vs[lower] + frac * (vs[upper] - vs[lower])

    # ── Block lifecycle ─────────────────────────────────────────────

    def _should_create_new_block(
        self, block: SessionBlock, entry: UsageEntry
    ) -> bool:
        """Start a new block if entry falls outside current window or
        there's a gap >= session_duration since last entry."""
        if entry.timestamp >= block.end_time:
            return True
        if block.entries:
            gap = entry.timestamp - block.entries[-1].timestamp
            if gap >= self.session_duration:
                return True
        return False

    def _new_block(self, entry: UsageEntry) -> SessionBlock:
        """Create a new block starting at the entry's hour boundary (UTC).

        Rounds start_time down to the nearest full hour, matching
        claude-monitor's SessionAnalyzer._round_to_hour() approach.
        This ensures consistent 5h windows aligned to clock hours.
        """
        start = entry.timestamp
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        elif start.tzinfo != timezone.utc:
            start = start.astimezone(timezone.utc)
        start = start.replace(minute=0, second=0, microsecond=0)
        end = start + self.session_duration
        return SessionBlock(
            id=start.isoformat(),
            start_time=start,
            end_time=end,
            token_counts=TokenCounts(),
        )

    def _add_entry(self, block: SessionBlock, entry: UsageEntry) -> None:
        """Add an entry to the block, aggregating tokens and per-model stats."""
        block.entries.append(entry)

        block.token_counts.input_tokens += entry.input_tokens
        block.token_counts.output_tokens += entry.output_tokens
        block.token_counts.cache_creation_tokens += entry.cache_creation_tokens
        block.token_counts.cache_read_tokens += entry.cache_read_tokens

        if entry.cost_usd:
            block.cost_usd += entry.cost_usd

        # Per-model stats (grouped by family: opus/sonnet/haiku/other)
        family = model_family(entry.model) if entry.model else "other"
        if family not in block.per_model_stats:
            block.per_model_stats[family] = {
                "input_tokens": 0, "output_tokens": 0,
                "cache_creation_tokens": 0, "cache_read_tokens": 0,
                "cost_usd": 0.0, "entries_count": 0,
            }
        stats = block.per_model_stats[family]
        stats["input_tokens"] += entry.input_tokens
        stats["output_tokens"] += entry.output_tokens
        stats["cache_creation_tokens"] += entry.cache_creation_tokens
        stats["cache_read_tokens"] += entry.cache_read_tokens
        stats["cost_usd"] += entry.cost_usd or 0.0
        stats["entries_count"] += 1

        if entry.model and entry.model not in block.models:
            block.models.append(entry.model)
        block.sent_messages_count += 1

    def _check_for_gap(
        self, last_block: SessionBlock, next_entry: UsageEntry
    ) -> SessionBlock | None:
        """Insert a gap block if inactivity exceeds session duration."""
        if not last_block.actual_end_time:
            return None
        gap_duration = next_entry.timestamp - last_block.actual_end_time
        if gap_duration < self.session_duration:
            return None
        return SessionBlock(
            id=f"gap-{last_block.actual_end_time.isoformat()}",
            start_time=last_block.actual_end_time,
            end_time=next_entry.timestamp,
            is_gap=True,
            token_counts=TokenCounts(),
        )

    def _finalize(self, block: SessionBlock) -> None:
        """Set actual_end_time to the last entry's timestamp."""
        if block.entries:
            block.actual_end_time = block.entries[-1].timestamp
        block.sent_messages_count = len(block.entries)

    def _mark_active(self, blocks: list[SessionBlock]) -> None:
        """Mark blocks whose end_time is still in the future."""
        now = datetime.now(timezone.utc)
        for block in blocks:
            if not block.is_gap and block.end_time > now:
                block.is_active = True

    # ── Limit detection ─────────────────────────────────────────────

    def _detect_single(self, raw: dict) -> dict | None:
        entry_type = raw.get("type")
        if entry_type == "system":
            return self._check_system_message(raw)
        if entry_type == "user":
            return self._check_user_message(raw)
        return None

    def _check_system_message(self, raw: dict) -> dict | None:
        """Check system messages for rate-limit / token-limit keywords."""
        content = raw.get("content", "")
        if not isinstance(content, str):
            return None
        cl = content.lower()
        if "limit" not in cl and "rate" not in cl:
            return None

        ts = _parse_timestamp(raw.get("timestamp"))
        if not ts:
            return None

        reset_time, wait_min = self._extract_wait_time(content, ts)
        return {
            "type": "system_limit",
            "timestamp": ts,
            "content": content,
            "reset_time": reset_time,
            "wait_minutes": wait_min,
        }

    def _check_user_message(self, raw: dict) -> dict | None:
        """Check user messages for tool_result containing 'limit reached'."""
        message = raw.get("message", {})
        content_list = message.get("content", [])
        if not isinstance(content_list, list):
            return None

        for item in content_list:
            if not isinstance(item, dict) or item.get("type") != "tool_result":
                continue
            tool_content = item.get("content", [])
            if not isinstance(tool_content, list):
                continue
            for ti in tool_content:
                if not isinstance(ti, dict):
                    continue
                text = ti.get("text", "")
                if not isinstance(text, str) or "limit reached" not in text.lower():
                    continue
                ts = _parse_timestamp(raw.get("timestamp"))
                if not ts:
                    continue
                reset_time = self._parse_reset_timestamp(text)
                return {
                    "type": "general_limit",
                    "timestamp": ts,
                    "content": text,
                    "reset_time": reset_time,
                }

        return None

    def _extract_wait_time(
        self, content: str, ts: datetime
    ) -> tuple[datetime | None, int | None]:
        """Extract 'wait N minutes' from content → compute reset time."""
        m = re.search(r"wait\s+(\d+)\s+minutes?", content.lower())
        if m:
            mins = int(m.group(1))
            return ts + timedelta(minutes=mins), mins
        return None, None

    def _parse_reset_timestamp(self, text: str) -> datetime | None:
        """Parse 'limit reached|<unix_timestamp>' from tool result text."""
        m = re.search(r"limit reached\|(\d+)", text)
        if m:
            try:
                return datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
            except (ValueError, OSError):
                pass
        return None


