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
  "action": "观望 · 不进场",
  "position": "0%",
  "rationale": "...",
  "levels": [
    {"key": "entry", "icon": "🏗️", "label": "建仓", "status": "不建议",
     "price": null, "cut": "底仓 40%",
     "reason": "周线下降 + 空头排列，净值 0.5395 跌破 MA20(0.5855)/MA60(0.6961)，右侧未确认..."},
    {"key": "add", "icon": "➕", "label": "加仓", "status": "不建议",
     "price": null, "cut": "金字塔 35→25%", "reason": "趋势为「下降」、无上升结构，加仓 = 接飞刀..."},
    {"key": "tp1", "icon": "①", "label": "止盈", "status": "若持有·触发即撤",
     "price": 0.5233, "cut": "减 30%", "reason": "跌破近端支撑（约 0.5233）说明短线走弱，先减 30% 锁利润。"},
    {"key": "tp2", "icon": "②", "label": "止盈", "status": "若持有·触发即撤",
     "price": 0.5855, "cut": "减 40%", "reason": "跌破 MA20(0.5855) + 死叉，中期趋势走弱，再减 40%。"},
    {"key": "trailing", "icon": "🛑", "label": "移动止盈", "status": "若持有·触发即撤",
     "price": 0.7292, "cut": "清仓", "reason": "从阶段高点 0.8286 回撤 12%（至 0.7292）触发..."},
    {"key": "stop", "icon": "✕", "label": "止损", "status": "若持有·触发即撤",
     "price": 0.5032, "cut": "清仓", "reason": "跌破前低 0.5032 → 更低低点、下跌结构延续，坚决清仓。"}
  ],
  "sector_signal": "🔴 同步下跌（板块 下降）— 基金 + 板块同跌，纪律观望",
  "deep_drawdown": true,
  "trailing_stop_pct": 0.120
}
```
> `status` 取值：建议 / 可轻仓试探 / 暂不建议 / 不建议 / 若持有·触发即撤 / ⚠️ 已触发（跌破型位当前净值已跌破该位）。每位都带 `reason`（引用具体净值/均线数字）。

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
