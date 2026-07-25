"""right_side_engine.py — 右侧交易决策引擎（skill 灵魂）

以"十年养基老手 + 右侧交易者"视角，把趋势信号转成可执行的作战卡：
建仓 / 加仓 / 止盈 / 止损 的具体净值位 + 建议状态 + 理由。

【右侧铁律】
  1. 不抄底不猜顶 —— 趋势确认才动手
  2. 宁可买贵 5%，不接飞刀
  3. 分批进、分批出
  4. 止损要快，止盈用移动止盈让利润奔跑

【参数】（用户已定）
  - 时间框架：周线为主（20/60 周）+ 日线辅助
  - 移动止盈：从阶段高点回撤 10%（平衡型）

每个操作位都给出 status（建议/不建议/若持有触发）+ reason（引用具体数字）。
本模块只做"机械决策"，agent 可在 stage2 用 agent_analysis.json 覆盖。
"""
from __future__ import annotations

TRAILING_STOP_PCT = 0.10   # 移动止盈回撤阈值（平衡型）
BASE_POSITION = 0.30       # 右侧底仓
FULL_POSITION = 0.50       # 主升浪确认后上限


def _build_levels(regime: str, struct: dict, breakout: dict, lv: dict,
                  sector: dict | None, trailing: float | None) -> list[dict]:
    """构建 6 个操作位，每个含 status + price + cut + reason（引用具体数字）。"""
    current = lv["current"]
    ma20w = lv["ma20w"]
    ma60w = lv["ma60w"]
    swing_low = lv["recent_swing_low"]
    stage_high = lv["stage_high_52w"]
    higher_lows = struct["higher_lows"]
    sec = sector or {}
    sec_regime = sec.get("sector_regime")
    sec_light = sec.get("light", "")
    sec_hint = f"；板块{sec_regime}{sec_light}共振走弱" if (sec_regime and sec_light) else ""

    # ---------- 建仓 ----------
    if regime == "下降":
        e_status, e_price = "不建议", None
        e_reason = (f"周线下降 + 空头排列，净值 {current} 跌破 MA20({ma20w})/MA60({ma60w})，"
                    f"右侧未确认{sec_hint}。纪律不抄底，等站稳 MA20 + 更高低点 + 突破。")
    elif regime == "震荡" and not (higher_lows and breakout["breakout"]):
        e_status, e_price = "暂不建议", ma20w
        e_reason = (f"震荡中缺更高低点 / 突破，右侧信号未现。关注位 MA20({ma20w})，"
                    f"站稳 + 企稳结构出现再议。")
    elif regime == "震荡":
        e_status, e_price = "可轻仓试探", ma20w
        e_reason = "震荡中出现更高低点 + 突破，右侧初现。轻仓试探，破前低即止损。"
    else:  # 上升
        e_status, e_price = "建议", ma20w
        e_reason = "周线上升 + 更高低点，趋势确认。底仓 30%，主升浪确认补到 50%。"

    # ---------- 加仓 ----------
    if regime == "上升" and higher_lows:
        a_status, a_price = "建议", ma20w
        a_reason = f"上升趋势中回踩 MA20({ma20w}) 不破时加仓（均线买法），金字塔 30→15→5%。"
    elif regime == "上升":
        a_status, a_price = "暂不建议", ma60w
        a_reason = f"上升但低点结构待确认，等更高低点。关注回踩 MA60({ma60w})。"
    else:
        a_status, a_price = "不建议", None
        a_reason = f"趋势为「{regime}」、无上升结构，加仓 = 接飞刀 / 摊低成本，违反右侧纪律。"

    return [
        {"key": "entry", "icon": "🏗️", "label": "建仓", "status": e_status, "price": e_price,
         "cut": "底仓 30%", "reason": e_reason},
        {"key": "add", "icon": "➕", "label": "加仓", "status": a_status, "price": a_price,
         "cut": "金字塔 15→5%", "reason": a_reason},
        {"key": "tp1", "icon": "①", "label": "止盈", "status": "若持有·触发即撤",
         "price": round(current * 0.97, 4), "cut": "减 30%",
         "reason": f"跌破近端支撑（约 {round(current * 0.97, 4)}）说明短线走弱，先减 30% 锁利润。"},
        {"key": "tp2", "icon": "②", "label": "止盈", "status": "若持有·触发即撤",
         "price": ma20w, "cut": "减 40%",
         "reason": f"跌破 MA20({ma20w}) + 死叉，中期趋势走弱，再减 40%。"},
        {"key": "trailing", "icon": "🛑", "label": "移动止盈", "status": "若持有·触发即撤",
         "price": trailing, "cut": "清仓",
         "reason": f"从阶段高点 {stage_high} 回撤 10%（至 {trailing}）触发，平衡型保护利润、让利润奔跑。"},
        {"key": "stop", "icon": "✕", "label": "止损", "status": "若持有·触发即撤",
         "price": swing_low, "cut": "清仓",
         "reason": f"跌破前低 {swing_low} → 更低低点、下跌结构延续，右侧纪律坚决清仓，不抱侥幸。"},
    ]


def decide(metrics: dict, signals: dict, sector: dict | None = None) -> dict:
    """把 metrics + signals + 板块(可选) → 右侧决策 dict（含 levels 每位带 status/reason）。"""
    trend = signals["trend"]
    struct = signals["structure"]
    breakout = signals["breakout_daily"]
    lv = signals["levels"]
    regime = trend["regime"]
    higher_lows = struct["higher_lows"]

    stage_high = lv["stage_high_52w"]
    trailing = round(stage_high * (1 - TRAILING_STOP_PCT), 4) if stage_high else None

    sec = sector or {}
    sec_hint = f"、板块{sec.get('sector_regime','?')}{sec.get('light','')}" if sec.get("available") else ""

    # 顶层 action
    if regime == "下降":
        action, position = "观望 · 不进场", "0%"
        rationale = f"周线下降趋势 + 空头排列{sec_hint}，右侧纪律第一条：不抄底。等站稳 MA20 + 更高低点 + 突破再谈建仓。"
    elif regime == "震荡":
        if higher_lows and breakout["breakout"]:
            action, position = "试探建仓（轻仓）", f"{int(BASE_POSITION * 100 * 0.6)}%"
            rationale = "震荡中出现更高低点 + 突破，右侧信号初现，可轻仓试探，破位即止损。"
        else:
            action, position = "观望 · 等待信号", "0%"
            rationale = "震荡无明确右侧信号（缺突破或更高低点）。备选关注位：站稳 20 周线。"
    else:  # 上升
        if higher_lows:
            action, position = "持有 · 回踩加仓", f"{int(FULL_POSITION * 100)}%"
            rationale = "周线上升 + 更高低点，趋势健康。回踩 20 周线加仓，用移动止盈保护利润。"
        else:
            action, position = "持有 · 暂不加仓", f"{int(BASE_POSITION * 100)}%"
            rationale = "上升但低点结构待确认。持有底仓，等结构确认再加仓。"

    levels = _build_levels(regime, struct, breakout, lv, sector, trailing)

    return {
        "fund_code": metrics.get("fund_code"),
        "action": action,
        "position": position,
        "rationale": rationale,
        "levels": levels,
        "sector_signal": _sector_label(sector),
        "deep_drawdown": lv["pct_below_stage_high"] < -25,
        "trailing_stop_pct": TRAILING_STOP_PCT,
    }


def _sector_label(sector: dict | None) -> str:
    """板块共振信号灯。从 compute_resonance 结果渲染成作战卡一行。"""
    if not sector:
        return "未接入"
    light = sector.get("light", "⚪")
    label = sector.get("label", "板块指数未获取")
    if sector.get("available"):
        return f"{light} {label}（板块 {sector.get('sector_regime','?')}）— {sector.get('advice','')}"
    return f"{light} {label}"


def _sector_news_md(news: dict | None) -> list[str]:
    """板块消息面 markdown 行（利好/利空/总结）。无消息返回空行占位。"""
    if not news or not (news.get("bullish") or news.get("bearish")):
        return [""]
    out = ["", f"## 📰 板块消息面（{news.get('sector', '板块')}，截至 {news.get('as_of', '')})", ""]
    if news.get("bullish"):
        out.append("**🔼 利好**")
        out += [f"- {b}" for b in news["bullish"]]
        out.append("")
    if news.get("bearish"):
        out.append("**🔽 利空**")
        out += [f"- {b}" for b in news["bearish"]]
        out.append("")
    if news.get("summary"):
        out.append(f"> 💡 {news['summary']}")
    return out + [""]


def _backtest_md(bt: dict | None) -> list[str]:
    """历史回测 markdown 行：信号在该基金的历史胜率/收益。无数据返回空行。"""
    if not bt or not bt.get("n_trades"):
        return [""]
    wr = bt["win_rate"]
    if wr is None:
        return ["", "## 📉 历史回测", "", "- 样本不足，无交易记录。", ""]
    tone = ("偏低，信号/参数可能不适合该标的，需谨慎或调参" if wr < 40
            else ("尚可" if wr < 55 else "较好"))
    return [
        "",
        "## 📉 历史回测（右侧信号在此基金的历史表现）",
        "",
        f"- 交易 **{bt['n_trades']}** 笔 · 胜率 **{wr}%** · 平均单笔 {bt['avg_return_pct']}% · 累计 {bt['total_return_pct']}%",
        f"- 单笔最大盈亏：+{bt['max_gain_pct']}% / {bt['max_loss_pct']}%",
        f"> ⚠️ 历史胜率{tone}。回测差 ≠ 一定不做，但说明信号在这只标的未经历史验证可靠，**别盲信单次作战卡**。",
        "",
    ]


def _valuation_md(val: dict | None) -> list[str]:
    """估值锚 markdown 行（PE 历史分位）。"""
    if not val or not val.get("available"):
        return ["", "## 💰 估值锚", "", f"- {(val or {}).get('reason', '估值不可用')}", ""]
    return [
        "",
        f"## 💰 估值锚（{val['index_name']} PE 近 {val['lookback_years']} 年）",
        "",
        f"- 当前 PE **{val['current_pe']}** · 历史 {val['pe_min']}~{val['pe_max']} · 分位 **{val['pe_percentile']}%**",
        f"- 判断：**{val['verdict']}**",
        f"> 分位高 = 贵，技术面右侧信号在此要警惕高位接盘；分位低 = 便宜，右侧安全垫更厚。",
        "",
    ]


# ---------------------------- 作战卡渲染 ----------------------------

def render_battle_card(decision: dict, metrics: dict, signals: dict, fund_code: str) -> str:
    """渲染右侧作战卡 markdown（净值位含建议状态 + 理由）。"""
    trend = signals["trend"]
    lv = signals["levels"]
    dd = metrics.get("drawdown", {})

    def _p(v):
        return f"{v}" if v is not None else "—"

    level_rows = []
    for l in decision["levels"]:
        price_txt = _p(l["price"])
        level_rows.append(f"| {l['icon']} {l['label']} | **{l['status']}** | {price_txt} | {l['cut']} | {l['reason']} |")

    lines = [
        f"# 右侧作战卡 · {fund_code}",
        "",
        f"**当前净值**: {_p(lv['current'])}（{metrics.get('latest_date','')}）　"
        f"**趋势**: `{trend['regime']}`（{trend['alignment']}）"
        + ("　⚠️ **深度回撤**" if decision.get("deep_drawdown") else ""),
        "",
        f"## ▶ 操作建议：**{decision['action']}**",
        "",
        f"> {decision['rationale']}",
        "",
        f"**建议仓位**：`{decision['position']}`",
        "",
        "## 🎯 关键净值位（含建议状态 + 理由）",
        "",
        "| 时机 | 建议 | 净值位 | 操作 | 理由 |",
        "|---|---|---|---|---|",
        *level_rows,
        "",
        "## 📊 风险指标",
        "",
        f"- 最大回撤: **{_p(dd.get('max_drawdown_pct'))}%**"
        f"（{dd.get('peak_date','')} → {dd.get('trough_date','')}），当前回撤 {_p(dd.get('current_drawdown_pct'))}%",
        f"- 年化波动: {_p(metrics.get('annualized_volatility_pct'))}%　"
        f"夏普: {_p(metrics.get('sharpe'))}　卡玛: {_p(metrics.get('calmar'))}",
        f"- 区间收益: 1月 {_p(metrics.get('period_returns_pct',{}).get('1m'))}% / "
        f"1年 {_p(metrics.get('period_returns_pct',{}).get('1y'))}% / "
        f"3年 {_p(metrics.get('period_returns_pct',{}).get('3y'))}%",
        f"- 距阶段高点(52周): **{_p(lv.get('pct_below_stage_high'))}%**",
        *_backtest_md(decision.get("backtest")),
        *_valuation_md(decision.get("valuation")),
        f"## 🟢🟡🔴 板块信号：{decision['sector_signal']}",
        *_sector_news_md(decision.get("sector_news")),
        "---",
        "⚠️ **免责**：以上为右侧交易策略框架的机械信号输出，**非投资建议**。"
        "场外基金 T+1、净值滞后，信号仅供决策参考，盈亏自负。",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import akshare as ak
    import pandas as pd
    from risk_metrics import compute_all
    from trend_signals import compute_signals

    df = ak.fund_open_fund_info_em(symbol="161725", period="近期")
    df = df.rename(columns={"净值日期": "date", "单位净值": "unit_nav", "日增长率": "daily_return"})
    df["date"] = pd.to_datetime(df["date"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    metrics = compute_all(df)
    metrics["fund_code"] = "161725"
    signals = compute_signals(df)
    decision = decide(metrics, signals)
    print(render_battle_card(decision, metrics, signals, "161725"))
