# Statusline 代码审查记忆

## 语言偏好
- 记忆文件和审查输出统一使用中文

## 项目规范
- 零外部依赖（仅标准库），Python >= 3.10
- 256 色 ANSI 转义码，逐字符渐变渲染
- 主题: Moonstone -- 色带: 银紫 -> 薰衣草 -> 天蓝 -> 薄荷
- 双层渲染: Shell (第 1 行) + Python (第 2 行及以后)
- `run.sh` 使用 `jq` 解析 JSON（Shell 侧的外部依赖）
- Python dataclasses: QuotaEntry 为 `frozen=True`，TokenCounts/SessionBlock 为可变

## 架构（重构后）
- 模块化结构: models.py, config.py, data/{reader,aggregator}.py, core/analyzer.py, render.py
- `run.sh` 将 hook JSON 写入 `/tmp/claude_statusline_debug.json`
- Python 完全基于 JSONL 扫描（不再读 hook JSON 内容），但 live 模式仍用 hook JSON mtime 做变更检测
- Live 模式使用基于 mtime 的变更检测 + 光标回退实现无闪烁刷新
- 信号处理器 (SIGINT/SIGTERM) 确保 live 模式下光标恢复
- 计划限额通过 `CLAUDE_PLAN_TYPE` 环境变量配置（默认: max5）
- 依赖方向: analyzer -> aggregator -> reader -> config/models（无循环依赖）
- `build_candidate_paths()` 发现目录: $CLAUDE_CONFIG_DIR, ~/.claude/projects, ~/.config/claude/projects
- Gap block: 间隔 >= session_duration 时插入 is_gap=True 占位 block
- Block start_time 取整到小时边界（UTC），5h 窗口与时钟对齐
- P90 三级回退: 命中 block -> 全部完成 block (output>0) -> min_limit -> plan limit

## 反复出现的 Bug 模式: 用 `or` 做回退值
- Python `or` 将 0, "", [], {} 视为假值 -- 用于数值回退时是错误的
- 出现位置: `_extract_entry_tokens()` (reader.py L134-139), 旧版 `extract_tokens()`
- 修复方案: 使用 `_get_first()` 模式（检查 `if k in d`）或显式 `is None` 判断
- 这是本代码库中排名第一的反复出现的反模式（第三次审查仍存在）

## 已标记的已知问题
- `run.sh` 中的调试代码写入 `/tmp/claude_statusline_debug.json` -- 安全性/性能隐患
- `run.sh` 中硬编码主机名 `DL_MacBookPro`（未使用的变量）
- `run.sh` 中多次调用 `jq`（8 次以上）-- 可以合并为 1 次
- aggregator.py 中的 `_parse_ts()` 与 reader.py 中的 `_parse_timestamp()` 功能重复（仍未修复）
- `_find_jsonl_files()` 回退到 PROJECTS_DIR 是冗余的（与候选路径相同）
- `strftime('%-I')` 是平台相关的（GNU 扩展，macOS 可用但 Windows 不行）
- `__main__.py` live 模式用 hook JSON mtime 做信号，但 docstring 声称 "fully JSONL-based"
- `load_usage_entries(hours_back=0)` 中 `if hours_back:` 将 0 视为假值

## 代码质量观察
- Python 代码质量明显高于 Shell 代码
- 整体具有良好的防御性解析和优雅降级机制
- SessionAnalyzer: _new_block -> _add_entry -> _finalize -> _mark_active
- `_MODEL_PRICING` 与参考项目 FALLBACK_PRICING 完全匹配（Opus/Sonnet/Haiku 三档）
- 定价用 model family key 比参考项目的 full model name key 更简洁
- render.py 的 pad_p bug 已通过动态 max_pct 修复
