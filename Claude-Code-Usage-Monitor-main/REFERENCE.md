# Claude-Code-Usage-Monitor 参考架构文档

> 此文件夹是第三方开源项目 [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) (v3.1.0, MIT License) 的快照，作为 statusline 项目的设计参考。本文档梳理其架构精华，供借鉴。

## 定位差异

| | statusline (本项目) | Claude-Code-Usage-Monitor (参考) |
|---|---|---|
| 运行方式 | Claude Code statusline hook (嵌入式) | 独立终端监控程序 (`claude-monitor`) |
| 渲染 | 纯 ANSI 256-color 转义码 | Rich 库 TUI (Live display + 表格) |
| 依赖 | 零外部依赖 | numpy, pydantic, rich, pytz 等 |
| 数据源 | hook JSON + JSONL 文件 | 直接扫描 `~/.claude/projects/` JSONL |
| 刷新模式 | single-shot (hook 每次调用) | 持续轮询 (后台线程, 可配间隔) |
| Plan 支持 | pro / max5 / max20 | pro / max5 / max20 / custom (P90 自适应) |

## 架构分层

```
cli/          → CLI 入口 + pydantic-settings 配置
core/         → 业务模型 + 计算逻辑 (纯函数, 零 I/O)
data/         → 数据读取 + 聚合 (JSONL 解析, 去重, 日/月聚合)
monitoring/   → 运行时协调 (后台线程 + 回调 + 缓存)
terminal/     → 终端管理 (主题检测 + WCAG 无障碍色彩)
ui/           → 展示层 (Rich 组件 + 进度条 + 表格视图)
utils/        → 工具集 (时区, 格式化, 通知, 模型识别)
```

## 值得借鉴的设计模式

### 1. 回调驱动的数据流 (Orchestrator 模式)

`monitoring/orchestrator.py` 是核心协调器：
- **后台线程** (`_monitoring_loop`) 按间隔轮询数据
- **回调注册** (`register_update_callback`) 将数据变更通知 UI
- **首次数据事件** (`_first_data_event`) 同步初始加载
- **会话追踪** (`SessionMonitor`) 检测会话切换

```
DataManager.get_data() → SessionMonitor.update() → callbacks → DisplayController
```

本项目的 `--live` 模式可参考此模式，将轮询与渲染解耦。

### 2. 分层缓存策略

`monitoring/data_manager.py`:
- TTL 缓存 (默认 5s)，失败时降级到陈旧缓存
- 指数退避重试 (最多 3 次)
- cache_age 属性便于诊断

### 3. Plan 配置中心化

`core/plans.py`:
- `PlanType` 枚举 + `PlanConfig` frozen dataclass
- `PLAN_LIMITS` 单一真相源
- Custom plan 支持 P90 自适应限额 (`p90_calculator.py`)
- 工厂函数 `get_token_limit(plan, blocks)` 统一入口

本项目的 `config.py` PLAN_LIMITS 字典是简化版，可参考其 PlanConfig 结构。

### 4. 模型定价计算

`core/pricing.py` — `PricingCalculator`:
- 按模型族 (Opus/Sonnet/Haiku) 分别定价
- 支持 input/output/cache_creation/cache_read 四类 token
- 缓存键: `model:in:out:cache_c:cache_r` → 避免重复计算
- 未知模型: 按名称模糊匹配 fallback 到 Sonnet 价格

### 5. 自适应终端主题

`terminal/themes.py`:
- `BackgroundDetector`: 三级检测 (COLORFGBG → 环境变量 → OSC 11 查询)
- WCAG AA 无障碍对比度标注
- Light/Dark/Classic 三套完整色板
- 线程安全的全局 `ThemeManager`

### 6. JSONL 去重机制

`data/reader.py`:
- 用 `message_id:request_id` 构建唯一哈希
- 跨文件去重 (同一条消息可能出现在多个 JSONL 中)
- `cutoff_time` 过滤历史数据

### 7. 聚合抽象

`data/aggregator.py`:
- `_aggregate_by_period(entries, period_key_func, ...)` 通用聚合
- `period_key_func` 控制粒度: 日 → `%Y-%m-%d`, 月 → `%Y-%m`
- `AggregatedPeriod` 支持按模型二级分桶

## 模块速查表

| 模块 | 核心类/函数 | 关键功能 |
|------|------------|---------|
| `cli/main.py` | `main()`, `_run_monitoring()` | CLI 入口, Rich Live 显示循环 |
| `cli/bootstrap.py` | `setup_environment()` | 环境初始化 (目录/日志/时区) |
| `core/models.py` | `UsageEntry`, `SessionBlock`, `BurnRate` | 数据模型 |
| `core/plans.py` | `Plans`, `PlanConfig`, `PLAN_LIMITS` | Plan 配置与限额查询 |
| `core/pricing.py` | `PricingCalculator` | 按模型计费 ($/MTok) |
| `core/calculations.py` | `BurnRateCalculator`, `calculate_hourly_burn_rate()` | 消耗速率 + 用量预测 |
| `core/p90_calculator.py` | `P90Calculator` | Custom plan P90 限额推算 |
| `core/settings.py` | `Settings` (pydantic-settings) | CLI 参数 + 持久化配置 |
| `data/reader.py` | `load_usage_entries()` | JSONL 读取 + 去重 + 费用计算 |
| `data/aggregator.py` | `UsageAggregator` | 日/月粒度聚合 |
| `data/analysis.py` | `analyze_usage()` | 5h 会话窗口切分 + 统计 |
| `monitoring/orchestrator.py` | `MonitoringOrchestrator` | 后台轮询 + 回调分发 |
| `monitoring/data_manager.py` | `DataManager` | TTL 缓存 + 重试 |
| `monitoring/session_monitor.py` | `SessionMonitor` | 会话切换检测 |
| `terminal/themes.py` | `ThemeManager`, `BackgroundDetector` | 主题管理 + 背景色自动检测 |
| `ui/display_controller.py` | `DisplayController` | UI 总控, 组装渲染数据 |
| `ui/progress_bars.py` | `TokenProgressBar`, `TimeProgressBar` | Rich 进度条组件 |
| `ui/table_views.py` | `TableViewsController` | 日/月表格视图 |
| `ui/session_display.py` | `SessionDisplayComponent` | 活跃会话详情渲染 |

## 运行命令

```bash
# 安装 (需要外部依赖)
pip install -e ".[dev]"

# 实时监控
claude-monitor --plan max5 --theme dark

# 日报视图
claude-monitor --view daily --timezone Asia/Bangkok

# 运行测试
pytest src/tests/ -m "not integration"
```
