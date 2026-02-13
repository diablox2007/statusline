# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Claude Code statusline hook that renders real-time usage/quota info in the terminal using ANSI 256-color gradients. Zero external dependencies — pure bash + Python stdlib.

## Running

```bash
# Statusline hook (how Claude Code invokes it — reads JSON from stdin):
echo '{"model":...}' | bash run.sh

# Python quota layer only (single-shot):
PYTHONPATH=src python3 -m statusline

# Python quota layer (live refresh every 10s):
PYTHONPATH=src python3 -m statusline --live
```

No build step, no install, no virtualenv needed. Requires `jq` for the shell layer and Python >= 3.10 for the quota layer.

## Architecture

Dual-layer rendering — `run.sh` outputs two lines:

**Line 1 (Shell):** `run.sh` parses the Claude Code hook JSON with `jq`, renders path, model, context progress bar, effort level, output style, session duration, and cost. All rendering uses per-character ANSI 256-color gradients via the `gradient_text()` function.

**Line 2 (Python):** `run.sh` calls `python3 -m statusline`, which computes 4 quota entries and renders them as aligned progress bars.

### Data Flow

```
Claude Code hook JSON (stdin)
  → run.sh writes to /tmp/claude_statusline_debug.json
  → run.sh renders Line 1 (gradient shell output)
  → python3 -m statusline
    → core/analyzer.py: compute_quota()
      1. Session %: read transcript JSONL directly (last entry per request)
         → output_tokens / plan_output_limit
      2. Weekly %: load_usage_entries() scans ~/.claude/projects/**/*.jsonl
         → aggregate output_tokens / weekly_limit
      3. Extra usage: JSONL cost estimation (flat Sonnet pricing)
         → monthly_cost / spending_cap
    → render.py: render_quota() → ANSI output
```

### Python Package Layout (`src/statusline/`)

| Module | Role |
|--------|------|
| `__main__.py` | Entry point: single-shot or `--live` mode |
| `config.py` | Constants, plan limits, MODEL_PRICING, env var overrides |
| `models.py` | Dataclasses: `QuotaEntry`, `QuotaData`, `TokenCounts`, `UsageEntry`, `SessionBlock` |
| `render.py` | ANSI renderer with aligned column output |
| `data/reader.py` | JSONL scanning, transcript reading, cost estimation |
| `data/aggregator.py` | 5h session blocks, P90 dynamic limits, gap/limit detection |
| `core/analyzer.py` | `compute_quota()` — builds all 4 quota entries |

## Quota Calculation Details

### 1. Session (output-token-based)
- Reads the current session's transcript JSONL via `read_transcript_output_tokens()`
- Claude Code writes multiple streaming entries per API request (avg 2.5, max 8), each with cumulative `message.usage.output_tokens`
- Dedup by `message_id:request_id`, keeping the **last** entry (final cumulative value)
- Formula: `sum(last_entry_per_request.output_tokens) / plan_output_limit`
- Plan limits: Pro=44K, Max5=88K, Max20=220K

### 2. Weekly (JSONL aggregated)
- Scans all `~/.claude/projects/**/*.jsonl` via `load_usage_entries()`
- Sums `output_tokens` since last weekly reset (Monday 4am local)
- Separate tracking for all-model and Sonnet-only
- Limits are empirical fits calibrated against `/usage` (not official values)

### 3. Extra Usage (cost-based)
- Sums estimated cost for all JSONL entries since month start
- Uses **flat Sonnet pricing** ($3/$15/$3.75 per M tokens) regardless of model
- Per-model Opus pricing ($5/$25/$6.25) overestimates by ~37%
- Accuracy: within 1% of `/usage` reported value

## Key Conventions

- **Theme: Moonstone (月光石)** — gradient band: silver-purple → lavender → sky-blue → mint (ANSI 256-color codes defined in `run.sh`)
- Context usage colors shift semantically: green (<60%), amber (60-80%), red (≥80%)
- `calc_remaining()` in `models.py` dynamically computes countdown strings from ISO 8601 timestamps
- `read_transcript_output_tokens()` is critical for session accuracy — `load_usage_entries()` dedup keeps first-seen entries which lose streaming cumulative values

## Configuration (Environment Variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_PLAN_TYPE` | `max5` | Plan tier: `pro`, `max5`, `max20` |
| `CLAUDE_WEEKLY_OUTPUT_LIMIT` | `300000` | Weekly all-model output token cap (empirical) |
| `CLAUDE_WEEKLY_SONNET_LIMIT` | `1000000` | Weekly Sonnet output token cap (empirical) |
| `CLAUDE_EXTRA_USAGE_LIMIT` | `50.0` | Monthly extra-usage spending cap (USD) |

## Known Limitations

- **No official billing API**: All quota data is reverse-engineered from JSONL files. Anthropic does not expose per-window usage data ([Issue #11535](https://github.com/anthropics/claude-code/issues/11535))
- **Weekly limits/reset are approximate**: Official weekly token limits are not published. Our defaults are empirical fits
- **5h window is rolling**: Starts from first message, not fixed clock. Our block alignment (hour boundary) is an approximation

## Reference

`Claude-Code-Usage-Monitor-main/` is a third-party reference project (not part of this codebase). See also [claude-code-usage-bar](https://github.com/leeguooooo/claude-code-usage-bar) and [ccusage](https://github.com/ryoppippi/ccusage).
