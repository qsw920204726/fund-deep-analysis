# 数据契约（JSON Schema）

> 所有产物落在 `.cache/{fund_code}/`，由脚本和 agent 协作读写。

## raw_data.json（stage1 脚本写）

```json
{
  "fund_code": "161725",
  "rows": 2717,
  "nav": [
    {"date": "2015-01-01", "unit_nav": 1.0000, "accum_nav": null, "daily_return": 0.0}
  ]
}
```
- 同步落地 `net_value.csv`（UTF-8-BOM，Excel 友好）。

## metrics.json（stage1 脚本写，risk_metrics.compute_all）

```json
{
  "fund_code": "161725",
  "period_returns_pct": {"1m": 4.51, "3m": -13.64, "6m": -25.19, "1y": -26.93, "3y": -48.64, "since_inception": -46.05},
  "annualized_return_pct": -5.56,
  "annualized_volatility_pct": 30.97,
  "sharpe": -0.244,
  "sortino": -0.36,
  "calmar": -0.08,
  "drawdown": {
    "max_drawdown_pct": -69.88,
    "peak_date": "2021-06-07",
    "trough_date": "2026-07-09",
    "current_drawdown_pct": -67.24
  },
  "latest_nav": 0.5395,
  "latest_date": "2026-07-24",
  "data_points": 2717
}
```

## signals.json（stage1 脚本写，trend_signals.compute_signals）

```json
{
  "weekly_bars": 571,
  "trend": {
    "regime": "下降",            // 上升 / 震荡 / 下降
    "alignment": "空头排列",      // 多头排列 / 空头排列 / 均线缠绕 / 数据不足
    "ma20w": 0.5855,
    "ma60w": 0.6961,
    "ma20_slope_up": false,
    "recent_cross": "无"         // 金叉(近) / 死叉(近) / 无
  },
  "structure": {"higher_lows": false, "recent_lows": [0.6928, 0.5032]},
  "breakout_daily": {"breakout": false, "recent_high": 0.6319, "pct_to_high": -14.62, "volume_surge": null},
  "levels": {
    "current": 0.5395,
    "ma5d": 0.5410,
    "ma10d": 0.5482,
    "ma20w": 0.5855,
    "ma60w": 0.6961,
    "recent_swing_low": 0.5032,
    "stage_high_52w": 0.8286,
    "pct_below_stage_high": -34.89
  }
}
```

## sector.json（stage1 脚本写，板块联动 Phase 2）

```json
{
  "available": true,
  "fund_code": "161725",
  "index_symbol": "sz399997",
  "fund_regime": "下降",
  "sector_regime": "下降",
  "sector_alignment": "空头排列",
  "light": "🔴",                 // 🟢强确认 / 🟡轻仓·观望 / 🔴警惕·同跌 / ⚪未获取
  "label": "同步下跌",
  "advice": "基金 + 板块同跌，纪律观望",
  "sector_returns_pct": {"1m": 4.7, "3m": -16.07, "1y": -29.9},
  "sector_id": {
    "main_sector": "白酒",
    "matched_keyword": "白酒",
    "index_symbols": ["sz399997"],
    "identification": "名称/重仓股含「白酒」"
  },
  "fund_name": "招商中证白酒指数(LOF)A",
  "fund_type": "指数型-股票",
  "holdings_year": "2024",
  "industry_snapshot": {"as_of": "2024-12-31", "top3": [["制造业", 94.48], ...]}
}
```
> `available=false` 时只有 light/label/advice/fund_code，板块共振降级展示。
> `volume_surge` 为场内 ETF 放量倍数（当日量/近20日均量）；场外基金为 null。

## rightside.json（stage1 脚本写，right_side_engine.decide）

```json
{
  "fund_code": "161725",
  "view": "empty",                // v0.5：empty=空仓视角 / holding=持仓视角
  "action": "观望 · 不进场",
  "position": "0%",
  "rationale": "...",
  "volume_note": "",              // v0.5：量能门控说明
  "sector_note": "",              // v0.5：板块门控说明
  "fast_note": "",                // v0.5：快速右侧说明
  "state": null,                  // v0.5：持仓视角时的 {"entry":..,"peak":..}
  "levels": [
    {"key": "entry", "icon": "🏗️", "label": "建仓", "status": "不建议",
     "price": null, "cut": "底仓 40%",
     "reason": "周线下降 + 空头排列，净值 0.5395 跌破 MA20(0.5855)/MA60(0.6961)，右侧未确认..."},
    {"key": "add", "icon": "➕", "label": "加仓", "status": "不建议",
     "price": null, "cut": "金字塔 35→25%", "reason": "趋势为「下降」、无上升结构，加仓 = 接飞刀..."},
    {"key": "tp1", "icon": "①", "label": "止盈", "status": "若持有·触发即撤",
     "price": 0.7142, "cut": "减 30%", "reason": "跌破 MA5d(0.7142)/MA10d(0.6876) 较高者说明短线走弱，先减 30% 锁利润。连续 2 日收盘低于该位才触发。"},
    {"key": "tp2", "icon": "②", "label": "止盈", "status": "若持有·触发即撤",
     "price": 0.7459, "cut": "减 40%", "reason": "跌破 MA20(0.7459) + 死叉，中期趋势走弱，再减 40%。"},
    {"key": "tp3", "icon": "③", "label": "止盈", "status": "⚠️ 已触发",
     "price": 0.8379, "cut": "清仓", "reason": "跌破 MA60(0.8379) + 空头排列，长期趋势破坏，清仓离场。"},
    {"key": "trailing", "icon": "🛑", "label": "移动止盈", "status": "参考·空仓视角",
     "price": 0.8897, "cut": "清仓", "reason": "空仓视角参考：自阶段高点 1.011 回撤 12%（至 0.8897）。实际持仓请用 --state holding 按入场后峰值跟踪。"},
    {"key": "stop", "icon": "✕", "label": "止损", "status": "若持有·触发即撤",
     "price": 0.643, "cut": "清仓", "reason": "跌破双轨止损位 0.643（已确认前低 0.751 / 最新可见低点 0.643 取低者，含 1% 缓冲）→ 更低低点、下跌结构延续，坚决清仓。"}
  ],
  "sector_signal": "🔴 同步下跌（板块 下降）— 基金 + 板块同跌，纪律观望",
  "deep_drawdown": true,
  "trailing_stop_pct": 0.120
}
```
> `status` 取值：建议 / 可轻仓试探 / 暂不建议 / 不建议 / 已持仓·不重复建仓 / 参考·空仓视角 / 若持有·触发即撤 / ⚠️ 已触发。
> v0.5：跌破型位（止盈/止损）需连续 2 日收盘确认，止损额外含 1% 缓冲；每位都带 `reason`（引用具体净值/均线数字）。
> 回测新增：`benchmark_return_pct`（同期买入持有）、`strategy_max_drawdown_pct`、`benchmark_max_drawdown_pct`、`avg_hold_weeks`（含手续费）。

## agent_analysis.json（Codex 介入写，stage2 读）

```json
{
  "commentary": "引用 rightside.json 具体数字的定性研判",
  "sector_news": {
    "sector": "白酒",
    "as_of": "2026-07-26",
    "bullish": ["带日期的利好摘要"],
    "bearish": ["带日期的利空摘要"],
    "summary": "消息面与技术面的冲突判断",
    "evidence_status": "verified",
    "sources": [
      {
        "title": "来源标题",
        "date": "2026-07-20",
        "url": "https://example.com/article",
        "stance": "bullish",
        "summary": "与板块判断直接相关的事实"
      }
    ]
  }
}
```

> `evidence_status` 只能是 `verified` 或 `unavailable`。`verified` 至少需要一个 source；
> source 的 `stance` 只能是 `bullish`、`bearish` 或 `neutral`，日期必须为 `YYYY-MM-DD`，URL 必须为 HTTP(S)。
> `unavailable` 必须使用空的 `bullish`、`bearish` 和 `sources`，并在 `summary` 明确说明无法核验外部证据。
> stage2 把 `commentary` 追加到作战卡末尾，并把 `sector_news` 与来源链接渲染进 HTML 报告。

## reports/{code}_{date}/battle-card.md（stage2 写）

最终产物，markdown 作战卡。Phase 3 升级为 Bloomberg 风格 HTML。


## v0.6 外部工具链字段（可选增强，缺失不影响主流程）

### sector.json.capital_flow（--enrich-flow 时脚本写，a-stock-data）

```json
{
  "available": true,
  "source": "a-stock-data",
  "as_of": "2026-08-08",
  "sector_board": {
    "board_type": "industry",
    "board": {"name": "软件开发", "code": "BK0737", "change_pct": -1.16,
              "main_net": -3866552832, "main_pct": -5.8, "rank": 495},
    "today_flow": {"date": "2026-08-07", "main_net": -3866552832,
                   "small_net": 3165765376, "medium_net": 686243328,
                   "large_net": -1547491584, "super_large_net": -2319061248}
  },
  "board_flow": {"industry": {"today": {"total": 496, "matched": [], "top5": [...]}, "5d": {...}},
                 "concept": {...}},
  "holdings": [{"name": "科大讯飞", "code": "002230", "weight": 11.19}],
  "stock_flow": [{"name": "科大讯飞", "code": "002230", "weight": 11.19,
                  "latest": {"date": "2026-08-07", "main_net": 1234567, "main_pct": 3.2}}],
  "dragon_tiger": {"total": 0, "matched": [], "holdings": []},
  "northbound": {"rows": [...], "latest": {"time": "15:00", "hgt_yi": -9.28, "sgt_yi": null}},
  "global_stock_hint": {"available": false, "hits": []}
}
```
- 所有金额单位=元（报告层转亿展示）；`matched` 为空表示板块资金未进流入榜（本身就是弱势信号）。
- 任一子项失败写 `{"error": "..."}` 并继续；东财 push2 被风控时自动降级 push2delay。
- `global_stock_hint.available=true` 时，agent 必须用 global-stock-data 核验对应港/美股后写入 agent_analysis.json。

### rightside.json.vibe_backtest（--vibe-backtest 时脚本写，Vibe-Trading MCP）

```json
{
  "available": true,
  "source": "Vibe-Trading MCP",
  "status": "ok",
  "metrics": {
    "total_return": -0.2717, "annual_return": -0.0584, "max_drawdown": -0.3715,
    "sharpe": -0.384, "win_rate": 0.3939, "trade_count": 33,
    "benchmark_return": -0.2523, "excess_return": -0.0194
  },
  "artifacts": {"run_card_md": "...", "equity": "...", "trades": "..."},
  "run_dir": "..."
}
```
- `metrics` 为比率（-0.2717 = -27.17%），报告层 ×100 展示；与周线主回测口径不同，仅作独立交叉验证。
- 失败时 `available=false` + `error`，报告区显示"未接入/降级"，不阻断出报告。
