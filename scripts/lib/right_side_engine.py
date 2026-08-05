"""right_side_engine.py — 右侧交易决策引擎（skill 灵魂）v0.5

以"十年养基老手 + 右侧交易者"视角，把趋势信号转成可执行的作战卡：
建仓 / 加仓 / 止盈 / 止损 的具体净值位 + 建议状态 + 理由。

【右侧铁律】
  1. 不抄底不猜顶 —— 趋势确认才动手
  2. 宁可买贵 5%，不接飞刀
  3. 分批进、分批出
  4. 止损要快，止盈用移动止盈让利润奔跑

v0.5 修复（对应评审问题）：
  A. 持仓状态机：decide(..., state={"entry":..,"peak":..}) 输出持仓视角；
     空仓视角下移动止盈仅作"52 周高点回撤参考"，不再误导显示"已触发"。
  B. 移动止盈：持仓视角锚定"入场后峰值"，从峰值回撤 12% 动态跟踪。
  C. 止损双轨：使用 trend_signals.stop_low（已确认 swing low 与最新可见低点取低者），
     触发需连续 2 日收盘低于止损位（prev_close + current），避免单日噪音扫损。
  D. 量能门控：场内 ETF 放量 <1.2 的突破判"缩量假突破"不进场；
     1.2~1.5 轻仓试探；>=1.5 正常试探。场外基金（无量）不受此限制。
  E. 板块门控：板块下降时"上升+更高低点"降权（100%→40%，加仓不建议）；
     基金震荡 + 板块上升 + 日线快速右侧（MA5>MA10 且自 20 日低点反弹>=3%）
     → "板块先行·轻仓关注"加速通道。
  F. 新增止盈③：跌破 MA60 周线清仓（补齐文档承诺的三档退出）。
  G. 止盈① 语义修正：取 max(MA5d, MA10d)，先破先减，与文档"跌破 5/10 日线减 30%"一致。
  H. 每个位给出 status + price + cut + reason（引用具体数字）。

本模块只做"机械决策"，agent 可在 stage2 用 agent_analysis.json 覆盖。
"""
from __future__ import annotations

TRAILING_STOP_PCT = 0.12   # 移动止盈回撤阈值（满仓型）
BASE_POSITION = 0.40       # 右侧底仓
FULL_POSITION = 1.00       # 主升浪确认后上限
STOP_BUFFER_PCT = 0.01     # 止损触发缓冲（需低于止损位 1% 才算破位，防贴线误触）
TRIGGER_CONFIRM_DAYS = 2   # 跌破型位需连续 N 日收盘确认
VOL_SURGE_CONFIRM = 1.5    # ETF 放量突破确认阈值
VOL_SURGE_SUSPECT = 1.2    # ETF 缩量突破警惕阈值


# ---------------------------- 触发判定 ----------------------------

def _broken(price: float | None, lv: dict, confirm_days: int = TRIGGER_CONFIRM_DAYS) -> bool:
    """跌破型位触发：连续 confirm_days 日收盘 <= 该位（含缓冲由调用方处理）。"""
    if price is None:
        return False
    closes = [lv.get("current"), lv.get("prev_close")]
    closes = [c for c in closes if c is not None]
    return len(closes) >= confirm_days and all(c <= price for c in closes[-confirm_days:])


def _stop_triggered(stop_price: float | None, lv: dict) -> bool:
    """止损触发：连续 2 日收盘跌破 止损位×(1-缓冲)。"""
    if stop_price is None:
        return False
    level = stop_price * (1 - STOP_BUFFER_PCT)
    return _broken(level, lv, confirm_days=2)


# ---------------------------- 决策矩阵 ----------------------------

def _build_levels(regime: str, struct: dict, breakout: dict, fast: dict, lv: dict,
                  sector: dict | None, trailing: float | None, view: str) -> list[dict]:
    """构建 7 个操作位，每个含 status + price + cut + reason（引用具体数字）。"""
    current = lv["current"]
    ma20w = lv["ma20w"]
    ma60w = lv["ma60w"]
    ma5d = lv.get("ma5d")
    ma10d = lv.get("ma10d")
    stop_low = lv.get("stop_low")
    pending_low = lv.get("pending_low")
    stage_high = lv["stage_high_52w"]
    higher_lows = struct["higher_lows"]
    vol = breakout.get("volume_surge")
    sec = sector or {}
    sec_regime = sec.get("sector_regime")
    sec_light = sec.get("light", "")
    sec_hint = f"；板块{sec_regime}{sec_light}共振走弱" if (sec_regime and sec_light and sec_regime != "上升") else ""
    vol_hint = f"；场内放量 {vol}x" if vol is not None else ""
    gap_entry = round((current / ma20w - 1) * 100, 2) if ma20w else None

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
        if vol is not None and vol < VOL_SURGE_SUSPECT:
            e_status, e_price = "暂不建议", ma20w
            e_reason = (f"虽有更高低点 + 突破，但场内放量仅 {vol}x（<{VOL_SURGE_SUSPECT}），"
                        f"疑似缩量假突破。等放量（≥{VOL_SURGE_CONFIRM}x）再进。")
        else:
            e_status, e_price = "可轻仓试探", ma20w
            e_reason = (f"震荡中出现更高低点 + 突破{vol_hint}，右侧初现。"
                        f"轻仓试探，破前低即止损。当前价距 MA20 溢价 {gap_entry}%。")
    elif view == "holding":
        e_status, e_price = "已持仓·不重复建仓", None
        e_reason = "当前处于持仓视角，建仓建议不适用；如需新开仓请用空仓视角。"
    else:  # 上升 + 空仓
        e_status, e_price = "建议", ma20w
        e_reason = (f"周线上升 + 更高低点，趋势确认。回踩 MA20({ma20w}) 挂单建仓，"
                    f"当前价距 MA20 溢价 {gap_entry}%（溢价过高勿追，等回踩）。")

    # ---------- 加仓 ----------
    if regime == "上升" and higher_lows:
        if vol is not None and breakout["breakout"] and vol < VOL_SURGE_SUSPECT:
            a_status, a_price = "暂不建议", ma20w
            a_reason = f"突破但放量仅 {vol}x（缩量突破别追），等放量确认。回踩 MA20({ma20w}) 不破仍可加。"
        elif sec_regime == "下降":
            a_status, a_price = "暂不建议", ma20w
            a_reason = f"板块{sec_regime}走弱，即使基金上升也不加仓（板块共振降权）。回踩 MA20({ma20w}) 观察。"
        else:
            a_status, a_price = "建议", ma20w
            a_reason = f"上升趋势中回踩 MA20({ma20w}) 不破时加仓（均线买法），金字塔 40→35→25%。"
    elif regime == "上升":
        a_status, a_price = "暂不建议", ma60w
        a_reason = f"上升但低点结构待确认，等更高低点。关注回踩 MA60({ma60w})。"
    else:
        a_status, a_price = "不建议", None
        a_reason = f"趋势为「{regime}」、无上升结构，加仓 = 接飞刀 / 摊低成本，违反右侧纪律。"

    # ---------- 止盈/止损位（跌破型触发，连续 2 日确认）----------
    # 止盈①：先破先减 —— 取 MA5d/MA10d 较高者（文档：跌破 5/10 日线减 30%）
    tp1_price = max(ma5d, ma10d) if (ma5d is not None and ma10d is not None) else round(current * 0.97, 4)
    tp2_price = ma20w
    tp3_price = ma60w
    stop_price = stop_low
    trailing_ref = trailing  # 已由 decide 按视角算好

    def _exit_status(price, kind="tp"):
        """跌破型位状态：连续 2 日收盘确认。"""
        if price is None:
            return "—"
        if kind == "stop":
            trig = _stop_triggered(price, lv)
        else:
            trig = _broken(price, lv)
        return "⚠️ 已触发" if trig else "若持有·触发即撤"

    def _exit_reason(base, price, kind="tp"):
        trig = (_stop_triggered(price, lv) if kind == "stop" else _broken(price, lv))
        if trig:
            return base + f" 当前净值 {current}（前收 {lv.get('prev_close')}）已连续跌破该位，信号已触发。"
        return base + f" 连续 2 日收盘低于该位才触发（当前 {current}）。"

    return [
        {"key": "entry", "icon": "🏗️", "label": "建仓", "status": e_status, "price": e_price,
         "cut": "底仓 40%", "reason": e_reason},
        {"key": "add", "icon": "➕", "label": "加仓", "status": a_status, "price": a_price,
         "cut": "金字塔 35→25%", "reason": a_reason},
        {"key": "tp1", "icon": "①", "label": "止盈", "status": _exit_status(tp1_price),
         "price": tp1_price, "cut": "减 30%",
         "reason": _exit_reason(f"跌破 MA5d({ma5d})/MA10d({ma10d}) 较高者说明短线走弱，先减 30% 锁利润。", tp1_price)},
        {"key": "tp2", "icon": "②", "label": "止盈", "status": _exit_status(tp2_price),
         "price": tp2_price, "cut": "减 40%",
         "reason": _exit_reason(f"跌破 MA20({ma20w}) + 死叉，中期趋势走弱，再减 40%。", tp2_price)},
        {"key": "tp3", "icon": "③", "label": "止盈", "status": _exit_status(tp3_price),
         "price": tp3_price, "cut": "清仓",
         "reason": _exit_reason(f"跌破 MA60({ma60w}) + 空头排列，长期趋势破坏，清仓离场。", tp3_price)},
        {"key": "trailing", "icon": "🛑", "label": "移动止盈",
         "status": (_exit_status(trailing_ref) if view == "holding" else "参考·空仓视角"),
         "price": trailing_ref, "cut": "清仓",
         "reason": (
             _exit_reason(
                 f"自入场后峰值 {trailing_ref / (1 - TRAILING_STOP_PCT):.4f} 回撤 {int(TRAILING_STOP_PCT*100)}%"
                 f"（至 {trailing_ref}）触发，动态跟踪保护利润。",
                 trailing_ref)
             if view == "holding"
             else f"空仓视角参考：自阶段高点 {stage_high} 回撤 {int(TRAILING_STOP_PCT*100)}%"
                  f"（至 {trailing_ref}）。实际持仓请用 --state holding --entry <成本> 按入场后峰值跟踪。")},
        {"key": "stop", "icon": "✕", "label": "止损", "status": _exit_status(stop_price, "stop"),
         "price": stop_price, "cut": "清仓",
         "reason": _exit_reason(
             f"跌破双轨止损位 {stop_price}（已确认前低 {lv.get('recent_swing_low')} / "
             f"最新可见低点 {pending_low} 取低者，含 1% 缓冲）→ 更低低点、下跌结构延续，坚决清仓。",
             stop_price, "stop")},
    ]


def decide(metrics: dict, signals: dict, sector: dict | None = None,
           state: dict | None = None) -> dict:
    """把 metrics + signals + 板块 + 持仓状态 → 右侧决策 dict。

    state: None → 空仓视角（默认）；{"entry": float, "peak": float} → 持仓视角。
    """
    trend = signals["trend"]
    struct = signals["structure"]
    breakout = signals["breakout_daily"]
    fast = signals.get("fast", {})
    lv = signals["levels"]
    regime = trend["regime"]
    higher_lows = struct["higher_lows"]
    view = "holding" if state else "empty"

    stage_high = lv["stage_high_52w"]
    # 移动止盈基准：持仓视角 = 入场后峰值；空仓视角 = 52 周高点（仅参考）
    if view == "holding":
        entry = float(state.get("entry") or lv["current"])
        peak = float(state.get("peak") or entry)
        trailing_base = max(entry, peak, lv["current"])
        trailing = round(trailing_base * (1 - TRAILING_STOP_PCT), 4) if trailing_base else None
    else:
        trailing = round(stage_high * (1 - TRAILING_STOP_PCT), 4) if stage_high else None

    sec = sector or {}
    sec_regime = sec.get("sector_regime")
    sec_hint = f"、板块{sec.get('sector_regime','?')}{sec.get('light','')}" if sec.get("available") else ""
    vol = breakout.get("volume_surge")

    # ---------- 顶层 action（含量能/板块门控 + 板块先行加速）----------
    volume_note = ""
    sector_note = ""
    fast_note = ""
    if regime == "下降":
        action, position = "观望 · 不进场", "0%"
        rationale = f"周线下降趋势 + 空头排列{sec_hint}，右侧纪律第一条：不抄底。等站稳 MA20 + 更高低点 + 突破再谈建仓。"
    elif regime == "震荡":
        if higher_lows and breakout["breakout"]:
            if vol is not None and vol < VOL_SURGE_SUSPECT:
                action, position = "观望 · 缩量假突破", "0%"
                volume_note = f"场内放量仅 {vol}x（<{VOL_SURGE_SUSPECT}），突破缺量，判假突破。"
                rationale = f"震荡中有更高低点 + 突破，但场内放量仅 {vol}x，缩量突破不可信{sec_hint}。等放量 ≥{VOL_SURGE_CONFIRM}x 再进。"
            elif vol is not None and vol < VOL_SURGE_CONFIRM:
                action, position = "试探建仓（放量不足·极轻）", "16%"
                volume_note = f"场内放量 {vol}x（{VOL_SURGE_SUSPECT}~{VOL_SURGE_CONFIRM}），仅极轻仓试探。"
                rationale = f"震荡中更高低点 + 突破，放量 {vol}x 略欠（≥{VOL_SURGE_CONFIRM} 为强），极轻仓试探，破位即止损。"
            else:
                action, position = "试探建仓（轻仓）", f"{int(BASE_POSITION * 100 * 0.6)}%"
                volume_note = f"场内放量 {vol}x（≥{VOL_SURGE_CONFIRM}）确认" if vol is not None else "场外基金无量，仅价突破"
                rationale = f"震荡中出现更高低点 + 突破{volume_note}，右侧信号初现，可轻仓试探，破位即止损。"
        elif sec_regime == "上升" and fast.get("daily_ma_align") and (fast.get("pct_off_low_20d") or 0) >= 3:
            action, position = "板块先行 · 轻仓关注", "16%"
            sector_note = f"板块{sec_regime}已右侧，基金周线仍在震荡但日线 MA5>MA10、自 20 日低点反弹 {fast.get('pct_off_low_20d')}%。"
            rationale = f"板块已右侧（{sec_regime}）、基金待启动：日线快速结构转多（MA5>MA10，反弹 {fast.get('pct_off_low_20d')}%）。轻仓关注，站稳 MA20 再加重。"
        else:
            action, position = "观望 · 等待信号", "0%"
            rationale = "震荡无明确右侧信号（缺突破或更高低点）" + (f"；板块{sec_regime}先行但基金日线结构未转多" if sec_regime == "上升" else "") + "。备选关注位：站稳 20 周线。"
    else:  # 上升
        if higher_lows:
            if sec_regime == "下降":
                target_pos, add_ok = f"{int(BASE_POSITION * 100)}%", False
                sector_note = f"基金上升但板块{sec_regime}走弱，共振降权：只持有底仓，不加仓。"
                rationale = f"周线上升 + 更高低点，但板块{sec_regime}走弱{sec_hint}，降权至底仓 {int(BASE_POSITION*100)}%，等板块转暖再加仓。"
            elif sec_regime == "震荡":
                target_pos, add_ok = "60%", True
                sector_note = f"板块{sec_regime}，共振一般：仓位控制在 60%。"
                rationale = f"周线上升 + 更高低点，板块{sec_regime}共振一般，仓位 60%，回踩 MA20 轻加。"
            else:
                target_pos, add_ok = f"{int(FULL_POSITION * 100)}%", True
                rationale = f"周线上升 + 更高低点{sec_hint}，趋势健康。回踩 20 周线加仓，用移动止盈保护利润。"
            if view == "empty":
                action = f"关注 · 等回踩建仓（目标 {target_pos}）"
                position = f"目标 {target_pos}"
                rationale = f"周线上升 + 更高低点，右侧成立。空仓者回踩 MA20 建底仓，目标仓位 {target_pos}，不追高。"
            else:
                action = "持有 · 回踩加仓" if add_ok else "持有 · 不加仓（板块走弱）"
                position = target_pos
        else:
            if view == "empty":
                action, position = "关注 · 等回踩建仓（目标 40%）", "目标 40%"
                rationale = f"周线上升但低点结构待确认{sec_hint}。空仓者等结构确认后再建仓，目标 40%。"
            else:
                action, position = "持有 · 暂不加仓", f"{int(BASE_POSITION * 100)}%"
                rationale = f"上升但低点结构待确认{sec_hint}。持有底仓，等结构确认再加仓。"

    if view == "holding":
        # 持仓视角：顶层动作改为持仓管理（建仓/加仓仅对空仓者有效）
        if "观望" in action or "等待" in action:
            action = "持仓管理 · 按退出位执行"
        elif action.startswith("持有"):
            pass  # 持有 · 回踩加仓 / 持有 · 不加仓 等，保留原义
        else:
            action = f"持仓管理 · {action}"
        position = "已持仓（按退出位执行）"

    levels = _build_levels(regime, struct, breakout, fast, lv, sector, trailing, view)

    return {
        "fund_code": metrics.get("fund_code"),
        "view": view,
        "action": action,
        "position": position,
        "rationale": rationale,
        "levels": levels,
        "sector_signal": _sector_label(sector),
        "deep_drawdown": lv["pct_below_stage_high"] < -25,
        "trailing_stop_pct": TRAILING_STOP_PCT,
        "volume_note": volume_note,
        "sector_note": sector_note,
        "fast_note": fast_note,
        "state": state if view == "holding" else None,
    }


def _sector_label(sector: dict | None) -> str:
    """板块共振信号灯。从 compute_resonance 结果渲染成一行。"""
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
    out = ["", f"## 📰 板块消息面（{news.get('sector', '板块')}，截至 {news.get('as_of', '')}）", ""]
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
    """历史回测 markdown 行：信号在该基金的历史胜率/收益（v0.5 含基准对比）。"""
    if not bt or not bt.get("n_trades"):
        return [""]
    wr = bt["win_rate"]
    if wr is None:
        return ["", "## 📉 历史回测", "", "- 样本不足，无交易记录。", ""]
    tone = ("偏低，信号/参数可能不适合该标的，需谨慎或调参" if wr < 40
            else ("尚可" if wr < 55 else "较好"))
    bench = ""
    if bt.get("benchmark_return_pct") is not None:
        bench = (f" · 同期买入持有 {bt['benchmark_return_pct']}%"
                 f"（策略回撤 {bt.get('strategy_max_drawdown_pct')}% vs 基准 {bt.get('benchmark_max_drawdown_pct')}%）")
    return [
        "",
        "## 📉 历史回测（右侧信号在此基金的历史表现）",
        "",
        f"- 交易 **{bt['n_trades']}** 笔 · 胜率 **{wr}%** · 平均单笔 {bt['avg_return_pct']}% · 累计 {bt['total_return_pct']}%{bench}",
        f"- 单笔最大盈亏：+{bt['max_gain_pct']}% / {bt['max_loss_pct']}%",
        f"> ⚠️ 历史胜率{tone}。回测含手续费，与买入持有对比仅供参考，**别盲信单次作战卡**。",
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
    """渲染右侧作战卡 markdown（净值位含建议状态 + 理由）。v0.5：+视角/门控说明。"""
    trend = signals["trend"]
    lv = signals["levels"]
    dd = metrics.get("drawdown", {})
    view = decision.get("view", "empty")
    view_badge = "🧍 空仓视角" if view == "empty" else "💼 持仓视角"

    def _p(v):
        return f"{v}" if v is not None else "—"

    level_rows = []
    for l in decision["levels"]:
        price_txt = _p(l["price"])
        level_rows.append(f"| {l['icon']} {l['label']} | **{l['status']}** | {price_txt} | {l['cut']} | {l['reason']} |")

    notes = []
    if decision.get("volume_note"):
        notes.append(f"- 📊 **量能**：{decision['volume_note']}")
    if decision.get("sector_note"):
        notes.append(f"- 🟢🟡🔴 **板块**：{decision['sector_note']}")
    if decision.get("fast_note"):
        notes.append(f"- ⚡ **快速右侧**：{decision['fast_note']}")
    notes_md = ("\n".join(notes) + "\n") if notes else ""

    lines = [
        f"# 右侧作战卡 · {fund_code}",
        "",
        f"**当前净值**: {_p(lv['current'])}（{metrics.get('latest_date','')}）　"
        f"**趋势**: `{trend['regime']}`（{trend['alignment']}）　**{view_badge}**"
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
        "## ⚙️ 门控与说明",
        "",
        f"- 移动止盈阈值：从基准回撤 **{decision['trailing_stop_pct']*100:.0f}%**（基准："
        + ("入场后峰值，动态跟踪" if view == "holding" else "52 周高点，仅空仓参考") + "）",
        "- 跌破型位（止盈/止损）需**连续 2 日收盘确认**；止损额外含 1% 缓冲",
        "- 场内 ETF 突破需放量确认（≥1.5x 强 / <1.2x 警惕）；场外基金无量，仅价突破",
        notes_md,
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
