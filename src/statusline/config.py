"""Configuration constants and plan limits."""

from __future__ import annotations

import os
from pathlib import Path

SESSION_HOURS = 5
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
HOOK_JSON = "/tmp/claude_statusline_debug.json"

PLAN_LIMITS: dict[str, dict] = {
    "pro":   {"output_limit": 19_000,  "cost_limit": 18.0,  "display": "Pro"},
    "max5":  {"output_limit": 88_000,  "cost_limit": 35.0,  "display": "Max 5x"},
    "max20": {"output_limit": 220_000, "cost_limit": 140.0, "display": "Max 20x"},
}

# Per-model API pricing (USD per million tokens), 2026.
# Currently only "sonnet" is used for cost estimation — see reader._estimate_cost().
# cache_read appears not billed.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "opus":   {"input": 5.0,  "output": 25.0, "cache_creation": 6.25},
    "sonnet": {"input": 3.0,  "output": 15.0, "cache_creation": 3.75},
    "haiku":  {"input": 1.0,  "output": 5.0,  "cache_creation": 1.25},
}

# Weekly output token limits (JSONL-based; calibrated against /usage output).
# These are *not* official values — they're empirical fits that approximate the
# percentages shown in Claude Code's /usage command.
WEEKLY_OUTPUT_LIMIT = int(os.environ.get("CLAUDE_WEEKLY_OUTPUT_LIMIT", "300000"))
WEEKLY_SONNET_LIMIT = int(os.environ.get("CLAUDE_WEEKLY_SONNET_LIMIT", "1000000"))

# Monthly extra-usage spending cap (USD)
EXTRA_USAGE_LIMIT = float(os.environ.get("CLAUDE_EXTRA_USAGE_LIMIT", "50.0"))

# P90 dynamic limit parameters
P90_MIN_SESSIONS = 5
P90_LIMIT_THRESHOLD = 0.95
COMMON_TOKEN_LIMITS = [19_000, 88_000, 220_000, 880_000]


def get_plan_type() -> str:
    return os.environ.get("CLAUDE_PLAN_TYPE", "max5")


def get_plan_limits() -> dict:
    return PLAN_LIMITS.get(get_plan_type(), PLAN_LIMITS["max5"])


def build_candidate_paths() -> list[Path]:
    """Build a deduplicated list of candidate data directories to scan.

    Discovery order:
      1. $CLAUDE_CONFIG_DIR (+ /projects if needed)
      2. ~/.claude/projects
      3. ~/.config/claude/projects
    """
    paths: list[Path] = []

    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if env_dir:
        env_path = Path(env_dir).expanduser()
        if env_path.name == ".claude":
            paths.append(env_path / "projects")
        else:
            paths.append(env_path / ".claude" / "projects")

    paths.extend([
        Path.home() / ".claude" / "projects",
        Path.home() / ".config" / "claude" / "projects",
    ])

    # Deduplicate (preserve order) and filter to existing dirs
    seen: set[Path] = set()
    result: list[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in seen and p.is_dir():
            seen.add(resolved)
            result.append(p)
    return result
