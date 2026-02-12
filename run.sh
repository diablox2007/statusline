#!/bin/bash
# Statusline entry: shell renders line 1 (Moonstone gradient), Python renders usage
# Usage: echo '{"model":...}' | bash run.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

input=$(cat)

# DEBUG: dump JSON input to temp file
echo "$input" > /tmp/claude_statusline_debug.json

# ============================================================
# === Line 1: Moonstone gradient (pure shell) ===
# ============================================================

# === Basic info ===
user=$(whoami)
host="DL_MacBookPro"
cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // ""')
home_dir="$HOME"

# Tidy path: replace $HOME with ~
if [[ "$cwd" == "$home_dir"* ]]; then
  display_path="~${cwd#"$home_dir"}"
else
  display_path="$cwd"
fi

# === Model info ===
model=$(echo "$input" | jq -r '.model.display_name // "Unknown"')

# === Context info ===
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // 0')
used_pct_int=$(printf "%.0f" "$used_pct" 2>/dev/null || echo "0")
# Format percentage: hide .0, show decimal only if needed
used_pct_raw=$(printf "%.1f" "$used_pct" 2>/dev/null || echo "0")
if [[ "$used_pct_raw" == *.0 ]]; then
  used_pct_formatted="${used_pct_raw%.0}"
else
  used_pct_formatted="$used_pct_raw"
fi
window_size=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
used_tokens=$(echo "$input" | jq -r "(.context_window.used_percentage // 0) * (.context_window.context_window_size // 0) / 100 | floor")

format_tokens() {
  local n="$1"
  if [ "$n" -ge 1000000 ] 2>/dev/null; then
    local whole=$((n / 1000000))
    local frac=$(( (n % 1000000) / 100000 ))
    if [ "$frac" -eq 0 ]; then
      echo "${whole}M"
    else
      echo "${whole}.${frac}M"
    fi
  elif [ "$n" -ge 1000 ] 2>/dev/null; then
    local whole=$((n / 1000))
    local frac=$(( (n % 1000) / 100 ))
    if [ "$frac" -eq 0 ]; then
      echo "${whole}K"
    else
      echo "${whole}.${frac}K"
    fi
  else
    echo "${n}"
  fi
}

input_k=$(format_tokens "$used_tokens")
window_k=$(format_tokens "$window_size")

# === Context progress bar ===
bar_width=10
bar_filled=$((used_pct_int * bar_width / 100))
bar_empty=$((bar_width - bar_filled))
CTX_BAR_FILLED=""
CTX_BAR_EMPTY=""
for ((i=0; i<bar_filled; i++)); do CTX_BAR_FILLED+="▪"; done
for ((i=0; i<bar_empty; i++)); do CTX_BAR_EMPTY+="▫"; done

# === Session duration ===
duration_ms=$(echo "$input" | jq -r '.cost.total_duration_ms // 0')
duration_min=$((duration_ms / 60000))
duration_sec=$(((duration_ms % 60000) / 1000))
if [ "$duration_min" -ge 60 ]; then
  duration_hr=$((duration_min / 60))
  duration_min=$((duration_min % 60))
  duration_fmt="${duration_hr}h${duration_min}m"
else
  duration_fmt="${duration_min}m${duration_sec}s"
fi

# === Session cost ===
session_cost=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
session_cost_fmt=$(printf "%.2f" "$session_cost" 2>/dev/null || echo "0.00")

# === Detect fast mode ===
style_name=$(echo "$input" | jq -r '.output_style.name // ""')
is_fast=false
if echo "$style_name" | grep -qi "fast"; then
  is_fast=true
fi

# === Read settings from local/user config ===
project_settings=".claude/settings.json"
local_settings=".claude/settings.local.json"

effort_level=$(jq -r '.effortLevel // "high"' ~/.claude/settings.json 2>/dev/null || echo "high")

output_style=""
if [ -f "$local_settings" ]; then
  output_style=$(jq -r '.outputStyle // ""' "$local_settings" 2>/dev/null)
fi
if [ -z "$output_style" ] && [ -f "$project_settings" ]; then
  output_style=$(jq -r '.outputStyle // ""' "$project_settings" 2>/dev/null)
fi
if [ -z "$output_style" ]; then
  output_style=$(jq -r '.outputStyle // "Default"' ~/.claude/settings.json 2>/dev/null || echo "Default")
fi

# ============================================================
# === Gradient Engine ===
# ============================================================
RST='\033[0m'
C_SEP='\033[38;5;238m'
C_EMPTY='\033[38;5;238m'
C_PAREN='\033[38;5;240m'

# Apply gradient colors per-character to an ASCII string
gradient_text() {
  local text="$1"
  shift
  local colors=("$@")
  local len=${#text}
  local num_colors=${#colors[@]}
  local result=""

  if [ "$len" -eq 0 ]; then return; fi

  for ((i=0; i<len; i++)); do
    if [ "$len" -eq 1 ]; then
      local cidx=0
    else
      local cidx=$(( i * (num_colors - 1) / (len - 1) ))
    fi
    result+="\033[38;5;${colors[$cidx]}m${text:$i:1}"
  done
  printf '%b' "$result"
}

# ============================================================
# === Theme: Moonstone (月光石) ===
# === 银紫 → 薰衣草 → 天蓝 → 薄荷 ===
# ============================================================

THEME_PATH=(146 146 147 147 153 153 117 117 81 81 80 80 115 115 151 151 157 157 158 194)
THEME_MODEL=(147 153 117 81 80 115 151)
THEME_DURATION=(157 158 158 194 194)

# ============================================================
# === Semantic Gradients ===
# ============================================================

# --- Context usage ---
if [ "$used_pct_int" -ge 80 ]; then
  CTX_COLORS=(131 167 174 175 211 218)
  CTX_BAR_COLOR='\033[38;5;174m'
elif [ "$used_pct_int" -ge 60 ]; then
  CTX_COLORS=(172 179 180 186 222 228)
  CTX_BAR_COLOR='\033[38;5;179m'
else
  CTX_COLORS=(73 79 80 86 115 157)
  CTX_BAR_COLOR='\033[38;5;79m'
fi

# --- Effort ---
case "$effort_level" in
  "low")
    EFFORT_DOTS="\033[38;5;167m•${C_EMPTY}◦◦"
    EFFORT_LABEL_TEXT="Low"
    EFFORT_LABEL_COLORS=(167 174 211)
    ;;
  "medium")
    EFFORT_DOTS="\033[38;5;67m•\033[38;5;74m•${C_EMPTY}◦"
    EFFORT_LABEL_TEXT="Medium"
    EFFORT_LABEL_COLORS=(67 74 110 110 117 153)
    ;;
  "high")
    EFFORT_DOTS="\033[38;5;72m•\033[38;5;78m•\033[38;5;115m•"
    EFFORT_LABEL_TEXT="High"
    EFFORT_LABEL_COLORS=(78 115 151 157)
    ;;
  *)
    EFFORT_DOTS="\033[38;5;72m•\033[38;5;78m•\033[38;5;115m•"
    EFFORT_LABEL_TEXT="$effort_level"
    EFFORT_LABEL_COLORS=(78 115 151 157)
    ;;
esac

# --- Output style ---
style_lower=$(echo "$output_style" | tr '[:upper:]' '[:lower:]')
case "$style_lower" in
  "default")      STYLE_COLORS=(243 245 247 249 250 251 252) ;;
  "explanatory")  STYLE_COLORS=(98 104 105 141 141 147 147 183 183 189 189) ;;
  "learning")     STYLE_COLORS=(72 78 114 114 150 150 151 157) ;;
  *)              STYLE_COLORS=(243 245 247 249 250 251 252) ;;
esac

# --- Cost ---
COST_COLORS=(186 222 228 229 230)

# === Clickable folder (OSC 8 hyperlink) ===
LINK_S="\033]8;;file://${cwd}\a"
LINK_E="\033]8;;\a"

# ============================================================
# === Output Line 1 ===
# ============================================================
ctx_nums="${input_k}/${window_k}"
ctx_pct="${used_pct_formatted}%"

# Path (theme gradient + clickable link)
printf '%b' "${LINK_S}"
gradient_text "$display_path" "${THEME_PATH[@]}"
printf '%b' "${LINK_E}${RST}"

# | Model
printf '%b' "${C_SEP}|${RST}"
gradient_text "$model" "${THEME_MODEL[@]}"
printf '%b' "${RST}"

# · ▪▪▪▫▫▫▫▫▫▫ (progress bar)
printf '%b' "${C_SEP}·${RST}${CTX_BAR_COLOR}${CTX_BAR_FILLED}${C_EMPTY}${CTX_BAR_EMPTY}${RST} "

# xxK/xxK (xx%)
gradient_text "$ctx_nums" "${CTX_COLORS[@]}"
printf '%b' "${RST} ${C_PAREN}("
gradient_text "$ctx_pct" "${CTX_COLORS[@]}"
printf '%b' "${C_PAREN})${RST}"

# | ••• High
printf '%b' "${C_SEP}|${RST}${EFFORT_DOTS}${RST} "
gradient_text "$EFFORT_LABEL_TEXT" "${EFFORT_LABEL_COLORS[@]}"
printf '%b' "${RST}"

# · Explanatory
printf '%b' "${C_SEP}·${RST}"
gradient_text "$output_style" "${STYLE_COLORS[@]}"
printf '%b' "${RST}"

# | 3m42s
printf '%b' "${C_SEP}|${RST}"
gradient_text "$duration_fmt" "${THEME_DURATION[@]}"
printf '%b' "${RST}"

# | $1.25
printf '%b' "${C_SEP}|${RST}"
gradient_text "\$${session_cost_fmt}" "${COST_COLORS[@]}"
printf '%b' "${RST}"

# ============================================================
# === Line 2+: Usage (Python) ===
# ============================================================
echo "$input" | PYTHONPATH="${SCRIPT_DIR}/src" python3 -m statusline 2>/dev/null
