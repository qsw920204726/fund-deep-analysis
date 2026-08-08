"""report_render.py — 右侧作战卡 HTML 报告渲染器 v0.6

把作战卡渲染成自包含的 Bloomberg 深色风格 HTML（单文件，无外部依赖，可手机分享）。

v0.5.1 信息架构重构：
  1. 结论先行：顶部 Hero 直接给"该不该动手 + 建议仓位 + 理由"
  2. 判定清单：周线趋势/更高低点/日线突破/量能/板块共振/深度回撤 六项 ✓/✗/△ 一眼扫完
  3. 价格定位条：当前净值相对 止损/MA20/MA60/52周高/移动止盈 的位置可视化为横向标尺
  4. 关键净值位分区：买入区（建仓/加仓）与卖出区（止盈①②③/移动止盈/止损）分开，
     状态 chip 用底色+文字；卖出区顶部写清"按退出位执行"具体规则（触发→动作）
  5. 回测对比条：策略 vs 买入持有 收益/最大回撤 横向条形对比
"""
from __future__ import annotations

from html import escape

import pandas as pd

from trend_signals import to_weekly, _ma, FAST_WEEKS, SLOW_WEEKS

# ---------- 配色（dark，文字/状态分离） ----------
C = {
    "bg": "#0d1117",
    "surface": "#161b22",
    "surface2": "#1c2230",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#8b949e",
    "accent": "#58a6ff",   # 净值主线（单系列主色）
    "good": "#3fb950",     # status: 建仓/加仓/上涨
    "warn": "#d29922",     # status: 止盈
    "bad": "#f85149",      # status: 止损/下跌
    "ma_fast": "#8b949e",  # MA20 参考线（中性灰虚线，非系列色）
    "ma_slow": "#6e7681",  # MA60 参考线
}

# 净值位卡片的图标 + 状态色（配文字标签，不单靠颜色）
LEVEL_STYLE = {
    "entry":   ("🏗️", "建仓", C["accent"]),
    "add":     ("➕", "加仓", C["good"]),
    "tp1":     ("①", "止盈", C["warn"]),
    "tp2":     ("②", "止盈", C["warn"]),
    "tp3":     ("③", "止盈", C["warn"]),
    "trailing":("🛑", "移动止盈", C["warn"]),
    "stop":    ("✕", "止损", C["bad"]),
}

# status → (tone_key, 底色透明度, 前缀)
STATUS_TONE = {
    "建议": ("good", "26", ""),
    "可轻仓试探": ("good", "26", ""),
    "已持仓·不重复建仓": ("muted", "22", "ℹ️ "),
    "暂不建议": ("warn", "26", "⏸ "),
    "不建议": ("bad", "26", "⛔ "),
    "若持有·触发即撤": ("muted", "22", "🔔 "),
    "⚠️ 已触发": ("bad", "2E", "🔴 "),
    "参考·空仓视角": ("muted", "22", "👁 "),
    "—": ("muted", "22", ""),
}


def _esc(s) -> str:
    return escape(str(s), quote=True)

# ---------------------------- 净值曲线 SVG（带 hover） ----------------------------

def _nav_chart_svg(weekly: pd.DataFrame, signals: dict, weeks: int = 156) -> str:
    """近 N 周净值主线 + MA20/MA60 中性虚线 + 关键位标注 + hover tooltip。"""
    w = weekly.iloc[-weeks:].reset_index(drop=True)
    price = w["unit_nav"]
    ma_f = _ma(weekly["unit_nav"], FAST_WEEKS).iloc[-weeks:].reset_index(drop=True)
    ma_s = _ma(weekly["unit_nav"], SLOW_WEEKS).iloc[-weeks:].reset_index(drop=True)

    # 价格域（含均线极值，留 5% padding）
    allvals = pd.concat([price, ma_f, ma_s]).dropna()
    vmin, vmax = float(allvals.min()), float(allvals.max())
    pad = (vmax - vmin) * 0.05 or 0.01
    vmin, vmax = vmin - pad, vmax + pad

    W, H, P = 820, 300, 36
    n = len(w)
    dates = [d.strftime("%Y-%m-%d") for d in w["date"]]

    def xy(i, v):
        x = P + (i / (n - 1)) * (W - 2 * P)
        y = (H - P) - ((v - vmin) / (vmax - vmin)) * (H - 2 * P)
        return x, y

    def path(series):
        pts = []
        for i, v in enumerate(series):
            if pd.isna(v):
                continue
            x, y = xy(i, float(v))
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    main_line = path(price)
    ma_f_line = path(ma_f)
    ma_s_line = path(ma_s)

    lv = signals["levels"]
    # 关键位水平虚线
    def hline(val, color, label):
        if val is None:
            return ""
        _, y = xy(0, float(val))
        return (f'<line x1="{P}" y1="{y:.1f}" x2="{W-P}" y2="{y:.1f}" '
                f'stroke="{color}" stroke-width="1" stroke-dasharray="2,4" opacity="0.5"/>'
                f'<text x="{W-P}" y="{y-4:.1f}" fill="{color}" font-size="10" text-anchor="end" opacity="0.8">{label} {val}</text>')

    # 当前点
    cx, cy = xy(n - 1, float(price.iloc[-1]))

    gridlines = ""
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        val = vmin + frac * (vmax - vmin)
        _, y = xy(0, val)
        gridlines += f'<line x1="{P}" y1="{y:.1f}" x2="{W-P}" y2="{y:.1f}" stroke="{C["border"]}" stroke-width="1" opacity="0.4"/>'
        gridlines += f'<text x="4" y="{y+3:.1f}" fill="{C["muted"]}" font-size="9">{val:.3f}</text>'

    return f'''
<svg id="navchart" viewBox="0 0 {W} {H}" class="chart" preserveAspectRatio="none">
  {gridlines}
  {hline(lv.get("ma60w"), C["ma_slow"], "MA60")}
  {hline(lv.get("ma20w"), C["ma_fast"], "MA20")}
  <polyline points="{ma_s_line}" fill="none" stroke="{C["ma_slow"]}" stroke-width="1.2" stroke-dasharray="4,3" opacity="0.55"/>
  <polyline points="{ma_f_line}" fill="none" stroke="{C["ma_fast"]}" stroke-width="1.2" stroke-dasharray="4,3" opacity="0.7"/>
  <polyline id="navline" points="{main_line}" fill="none" stroke="{C["accent"]}" stroke-width="1.8" stroke-linejoin="round"/>
  <circle id="navdot" cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{C["accent"]}" stroke="{C["bg"]}" stroke-width="1.5"/>
  <line id="cross" x1="0" y1="{P}" x2="0" y2="{H-P}" stroke="{C["text"]}" stroke-width="1" opacity="0" stroke-dasharray="3,3"/>
  <circle id="hoverdot" r="3.5" fill="{C["text"]}" stroke="{C["bg"]}" stroke-width="1.5" opacity="0"/>
</svg>
<div id="tooltip" class="tooltip"></div>
<script>
(function(){{
  const svg=document.getElementById('navchart');
  const tip=document.getElementById('tooltip');
  const cross=document.getElementById('cross');
  const hdot=document.getElementById('hoverdot');
  const line=document.getElementById('navline');
  const pts=line.getAttribute('points').trim().split(/\\s+/).map(p=>p.split(',').map(Number));
  const dates={dates!r};
  const vals=[{','.join(f'{float(v):.4f}' for v in price)}];
  function pt(e){{
    const r=svg.getBoundingClientRect();
    const x=(e.clientX-r.left)/r.width*{W};
    let best=0,bd=1e9;
    for(let i=0;i<pts.length;i++){{if(Math.abs(pts[i][0]-x)<bd){{bd=Math.abs(pts[i][0]-x);best=i;}}}}
    const px=pts[best][0],py=pts[best][1];
    hdot.setAttribute('cx',px);hdot.setAttribute('cy',py);hdot.setAttribute('opacity',1);
    cross.setAttribute('x1',px);cross.setAttribute('x2',px);cross.setAttribute('opacity',0.5);
    tip.style.opacity=1;
    tip.innerHTML=dates[best]+'<br><b>'+vals[best].toFixed(4)+'</b>';
    const left=Math.min(px/{W}*100+1, 78);
    tip.style.left=left+'%';
  }}
  svg.addEventListener('mousemove',pt);
  svg.addEventListener('mouseleave',()=>{{hdot.setAttribute('opacity',0);cross.setAttribute('opacity',0);tip.style.opacity=0;}});
}})();
</script>'''


# ---------------------------- 状态 chip / 净值位卡片 ----------------------------

def _status_chip(status: str) -> str:
    tone, alpha, prefix = STATUS_TONE.get(status, ("accent", "26", ""))
    color = C.get(tone, C["accent"])
    return (f'<span class="status-chip" style="background:{color}{alpha};color:{color};'
            f'border:1px solid {color}44">{_esc(prefix)}{_esc(status)}</span>')


def _level_card(level: dict) -> str:
    status = level.get("status", "")
    icon = level.get("icon", "")
    label = level.get("label", "")
    price_txt = f"{level['price']}" if level.get("price") is not None else "—"
    cut = level.get("cut", "")
    reason = level.get("reason", "")
    tone, _, _ = STATUS_TONE.get(status, ("accent", "26", ""))
    color = C.get(tone, C["accent"])
    return f'''
    <div class="level-card" style="border-left:3px solid {color}">
      <div class="level-head">
        <span class="level-icon">{icon}</span>
        <span class="level-label">{_esc(label)}</span>
        {_status_chip(status)}
      </div>
      <div class="level-price-row">
        <span class="level-price" style="color:{color}">{_esc(price_txt)}</span>
        <span class="level-cut">{_esc(cut)}</span>
      </div>
      <div class="level-trigger">{_esc(reason)}</div>
    </div>'''


def _exec_rule_line(levels: list[dict]) -> str:
    """把卖出区的'按退出位执行'翻译成一句话：触发哪个位→执行什么动作。"""
    parts = []
    for l in levels:
        price = l.get("price")
        price_txt = f"{price}" if price is not None else "—"
        parts.append(f"{l['icon']} 跌破 {price_txt} → {l.get('cut','')}")
    rule = " · ".join(parts)
    return (f'<div class="exec-rule">📋 <b>按退出位执行</b>：价格跌破下列任一净值位且连续 2 日收盘确认，'
            f'立即执行对应动作，不猜不扛 —— {rule}</div>')


def _levels_groups(decision: dict) -> str:
    """买入区 / 卖出区 分组渲染。卖出区附'按退出位执行'说明。"""
    levels = decision.get("levels", [])
    buy_keys = {"entry", "add"}
    sell_keys = {"tp1", "tp2", "tp3", "trailing", "stop"}
    buy = [l for l in levels if l["key"] in buy_keys]
    sell = [l for l in levels if l["key"] in sell_keys]

    def group(title, items, color, hint, extra=""):
        if not items:
            return ""
        cards = "".join(_level_card(l) for l in items)
        return f'''
      <div class="level-group" style="border-top:2px solid {color}">
        <div class="level-group-head">
          <span style="color:{color}">{title}</span>
          <span class="level-group-hint">{_esc(hint)}</span>
        </div>
        {extra}
        <div class="levels-grid">{cards}</div>
      </div>'''

    return (group("🟢 买入区", buy, C["good"],
                  "给空仓者看：现在能不能买、买在哪")
            + group("🔴 卖出区", sell, C["bad"],
                    "给持仓者看：触发哪个位就执行哪个动作",
                    extra=_exec_rule_line(sell)))

# ---------------------------- 判定清单 / 价格定位条 ----------------------------

def _verdict_strip(signals: dict, sector: dict | None, decision: dict) -> str:
    """六项判定清单：一眼看出'为什么是现在这个结论'。"""
    trend = signals["trend"]
    struct = signals["structure"]
    bo = signals["breakout_daily"]
    lv = signals["levels"]

    def item(label, value, state, note=""):
        if state == "ok":
            dot, color = "✓", C["good"]
        elif state == "no":
            dot, color = "✗", C["bad"]
        elif state == "warn":
            dot, color = "△", C["warn"]
        else:
            dot, color = "—", C["muted"]
        note_html = f'<span class="v-note">{_esc(note)}</span>' if note else ""
        return (f'<div class="verdict-item"><span class="v-dot" style="color:{color}">{dot}</span>'
                f'<span class="v-label">{_esc(label)}</span>'
                f'<span class="v-value">{_esc(value)}</span>{note_html}</div>')

    regime = trend["regime"]
    t_state = "ok" if regime == "上升" else ("no" if regime == "下降" else "warn")
    hl_state = "ok" if struct["higher_lows"] else "no"
    bo_state = "ok" if bo["breakout"] else "no"
    vol = bo.get("volume_surge")
    if vol is None:
        vol_txt, vol_state = "场外无量", "muted"
    elif vol >= 1.5:
        vol_txt, vol_state = f"{vol}x 放量", "ok"
    elif vol >= 1.2:
        vol_txt, vol_state = f"{vol}x 一般", "warn"
    else:
        vol_txt, vol_state = f"{vol}x 缩量", "no"

    sec = sector or {}
    sec_state = "muted"
    if sec.get("available"):
        light = sec.get("light")
        sec_state = "ok" if light == "🟢" else ("no" if light == "🔴" else "warn")
    sec_txt = f"{sec.get('light','⚪')} {sec.get('sector_regime') or '未接入'}"

    dd = lv.get("pct_below_stage_high")
    dd_state = "warn" if (dd is not None and dd < -25) else "ok"
    dd_txt = f"{dd}%"

    return f'''
    <div class="verdict-grid">
      {item("周线趋势", f"{regime}·{trend['alignment']}", t_state)}
      {item("更高低点", "是" if struct["higher_lows"] else "否", hl_state,
            "结构" if not struct.get("recent_lows") else f"低点 {struct['recent_lows'][-1]}")}
      {item("日线突破", "是" if bo["breakout"] else "否", bo_state,
            f"距60日高 {bo.get('pct_to_high')}%" if not bo["breakout"] else "")}
      {item("量能", vol_txt, vol_state)}
      {item("板块共振", sec_txt, sec_state)}
      {item("深度回撤", dd_txt, dd_state, "警惕飞刀" if dd_state == "warn" else "")}
    </div>'''


def _price_gauge(signals: dict, decision: dict) -> str:
    """当前净值相对关键位的横向标尺。"""
    lv = signals["levels"]
    current = lv.get("current")
    if current is None:
        return ""
    level_map = {l["key"]: l for l in decision.get("levels", [])}
    marks = []
    def add(key, label, color, is_current=False):
        price = None
        if key == "current":
            price = current
        elif key == "ma20w":
            price = lv.get("ma20w")
        elif key == "ma60w":
            price = lv.get("ma60w")
        elif key == "stage_high":
            price = lv.get("stage_high_52w")
        elif key in level_map:
            price = level_map[key].get("price")
        if price is None:
            return
        marks.append({"label": label, "price": float(price), "color": color, "cur": is_current})

    add("current", "现价", C["accent"], True)
    add("stop", "止损", C["bad"])
    add("ma20w", "MA20周", C["ma_fast"])
    add("ma60w", "MA60周", C["ma_slow"])
    add("stage_high", "52周高", C["muted"])
    add("trailing", "移动止盈", C["warn"])
    if len(marks) < 2:
        return ""

    lo = min(m["price"] for m in marks)
    hi = max(m["price"] for m in marks)
    if hi - lo < 1e-9:
        hi = lo + 1e-9
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad

    def pct(v):
        return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))

    markers = ""
    for m in marks:
        x = pct(m["price"])
        if m["cur"]:
            markers += (f'<div class="g-mark cur" style="left:{x:.1f}%;color:{m["color"]}">'
                        f'<b>{_esc(m["label"])} {m["price"]:.4f}</b></div>')
        else:
            markers += (f'<div class="g-mark" style="left:{x:.1f}%;color:{m["color"]}">'
                        f'<span class="g-dot" style="background:{m["color"]}"></span>'
                        f'{_esc(m["label"])} {m["price"]:.4f}</div>')

    return f'''
    <div class="gauge-wrap">
      <div class="gauge">
        <div class="g-track"></div>
        {markers}
      </div>
      <div class="g-range">
        <span style="color:var(--muted)">{lo:.4f}</span>
        <span style="color:var(--muted)">{hi:.4f}</span>
      </div>
    </div>'''


# ---------------------------- KPI / 回测 / 板块 / 估值 ----------------------------

def _kpi_tile(label, value, sub, tone=None) -> str:
    color = {"good": C["good"], "bad": C["bad"]}.get(tone, C["text"])
    return f'''
    <div class="kpi">
      <div class="kpi-label">{_esc(label)}</div>
      <div class="kpi-value" style="color:{color}">{_esc(value)}</div>
      <div class="kpi-sub">{_esc(sub)}</div>
    </div>'''


def _kpi_row(metrics: dict, signals: dict) -> str:
    dd = metrics["drawdown"]
    pr = metrics["period_returns_pct"]
    regime = signals["trend"]["regime"]
    regime_tone = {"上升": "good", "下降": "bad"}.get(regime)
    tiles = [
        _kpi_tile("趋势", regime, signals["trend"]["alignment"], regime_tone),
        _kpi_tile("最大回撤", f"{dd['max_drawdown_pct']}%", f"当前 {dd['current_drawdown_pct']}%", "bad"),
        _kpi_tile("年化波动", f"{metrics['annualized_volatility_pct']}%", "高风险指标" if metrics["annualized_volatility_pct"] and metrics["annualized_volatility_pct"] > 25 else ""),
        _kpi_tile("夏普", f"{metrics['sharpe']}", "风险调整后收益", "good" if metrics["sharpe"] and metrics["sharpe"] > 0 else ("bad" if metrics["sharpe"] and metrics["sharpe"] < 0 else None)),
        _kpi_tile("卡玛", f"{metrics['calmar']}", "回撤调整后", "good" if metrics["calmar"] and metrics["calmar"] > 0 else ("bad" if metrics["calmar"] and metrics["calmar"] < 0 else None)),
        _kpi_tile("距高点", f"{signals['levels']['pct_below_stage_high']}%", "52 周阶段高点", "bad" if signals["levels"]["pct_below_stage_high"] < -25 else None),
        _kpi_tile("近 1 年", f"{pr.get('1y')}%", "区间收益", "good" if pr.get("1y") and pr["1y"] > 0 else ("bad" if pr.get("1y") and pr["1y"] < 0 else None)),
        _kpi_tile("近 3 年", f"{pr.get('3y')}%", "区间收益", "good" if pr.get("3y") and pr["3y"] > 0 else ("bad" if pr.get("3y") and pr["3y"] < 0 else None)),
    ]
    return f'<div class="kpi-row">{"".join(tiles)}</div>'


def _compare_bar(label_a, va, label_b, vb, fmt="%") -> str:
    """策略 vs 基准 对比横条。"""
    if va is None or vb is None:
        return ""
    vmax = max(abs(va), abs(vb), 1e-9)

    def bar(label, v, color):
        w = abs(v) / vmax * 100
        return (f'<div class="c-bar-row"><span class="c-bar-label">{_esc(label)}</span>'
                f'<div class="c-bar-track"><div class="c-bar-fill" style="width:{w:.1f}%;background:{color}"></div></div>'
                f'<span class="c-bar-val" style="color:{color}">{v}{fmt}</span></div>')

    return f'<div class="c-bars">{bar(label_a, va, C["accent"])}{bar(label_b, vb, C["muted"])}</div>'


def _backtest_block(bt: dict | None) -> str:
    """历史回测卡片：胜率/收益 + 策略 vs 基准对比。"""
    if not bt or not bt.get("n_trades") or bt.get("win_rate") is None:
        return ""
    wr = bt["win_rate"]
    tone_key = "bad" if wr < 40 else ("good" if wr >= 55 else None)
    verdict = "偏低" if wr < 40 else ("尚可" if wr < 55 else "较好")
    compare = ""
    if bt.get("benchmark_return_pct") is not None:
        compare = f'''
      <div class="c-title">策略 vs 同期买入持有（含手续费）</div>
      {_compare_bar("策略累计", bt['total_return_pct'], "买入持有", bt['benchmark_return_pct'])}
      {_compare_bar("策略最大回撤", bt['strategy_max_drawdown_pct'], "基准最大回撤", bt['benchmark_max_drawdown_pct'])}'''
    return f'''
<div class="card">
  <div class="section-title">📉 历史回测（信号在此基金的历史表现 · 含手续费）</div>
  <div class="kpi-row">
    {_kpi_tile("交易笔数", bt['n_trades'], "", None)}
    {_kpi_tile("胜率", f"{wr}%", verdict, tone_key)}
    {_kpi_tile("平均单笔", f"{bt['avg_return_pct']}%", "", "bad" if bt['avg_return_pct'] < 0 else "good")}
    {_kpi_tile("累计", f"{bt['total_return_pct']}%", "", tone_key)}
    {_kpi_tile("平均持仓", f"{bt.get('avg_hold_weeks')}周", "", None) if bt.get('avg_hold_weeks') is not None else ""}
  </div>
  {compare}
  <div class="sub" style="margin-top:10px">单笔最大盈亏：+{bt['max_gain_pct']}% / {bt['max_loss_pct']}% · 样本 {bt['n_trades']} 笔，统计意义有限</div>
  <div style="margin-top:10px;padding:10px;background:var(--surface2);border-left:3px solid {C['warn']};border-radius:6px;font-size:13px">⚠️ 历史胜率{verdict}——回测差 ≠ 不能做，但信号未经历史验证可靠，<b>别盲信单次作战卡</b>。</div>
</div>'''


def _valuation_block(val: dict | None) -> str:
    """估值锚卡片：PE 历史分位。"""
    if not val or not val.get("available"):
        return (f'<div class="card"><div class="section-title">💰 估值锚</div>'
                f'<div class="sub" style="padding:10px">{_esc((val or {}).get("reason", "估值不可用"))}</div></div>')
    pct = val["pe_percentile"]
    tone = "good" if pct < 40 else ("bad" if pct >= 80 else None)
    color = {"good": C["good"], "bad": C["bad"]}.get(tone, C["text"])
    return f'''
<div class="card">
  <div class="section-title">💰 估值锚（{_esc(val['index_name'])} PE 近 {val['lookback_years']} 年）</div>
  <div class="kpi-row">
    {_kpi_tile("当前PE", val['current_pe'], "")}
    {_kpi_tile("历史分位", f"{pct}%", val['verdict'], tone)}
    {_kpi_tile("近5年区间", f"{val['pe_min']}~{val['pe_max']}", "")}
  </div>
  <div style="margin-top:10px;padding:10px;background:var(--surface2);border-left:3px solid {color};border-radius:6px;font-size:13px">估值 <b style="color:{color}">{val['verdict']}</b>——分位高=贵警惕高位接盘，分位低=便宜右侧安全垫厚。</div>
</div>'''

# v0.6 外部工具链区块（由补丁脚本拼入 report_render.py，位于 _sector_block 之前）

def _fmt_yi(v, nd: int = 2) -> str:
    """元 → 亿（带符号）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if f == 0:
        return "0"
    return f"{f / 1e8:+.{nd}f}亿"


def _pct(v, nd: int = 1) -> str:
    """比率 → 百分比字符串（比率小于 1 时视为小数）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(f) <= 1:
        f = f * 100
    return f"{f:+.1f}%"


def _capital_flow_block(sector: dict | None) -> str:
    """资金面验证卡片（a-stock-data）：板块资金流 + 重仓股资金流 + 龙虎榜 + 北向。"""
    cf = (sector or {}).get("capital_flow") or {}
    if not cf.get("available"):
        err = cf.get("error") or "未启用 --enrich-flow"
        return ('<div class="card"><div class="section-title">💧 资金面验证（外部工具链）</div>'
                f'<div class="sub" style="padding:10px">未接入：{_esc(err)}</div></div>')
    parts = []

    sb = cf.get("sector_board") or {}
    if sb.get("board"):
        b = sb["board"]
        tf = sb.get("today_flow") or {}
        name = b.get("name", "—")
        code = b.get("code", "")
        rank = b.get("rank")
        chg = b.get("change_pct")
        rank_txt = f"主力净流入第 {rank} 名（全市场板块）" if rank else "主力净流入排名未获取"
        tone = C["bad"] if (tf.get("main_net") or 0) < 0 else C["good"]
        main_txt = _fmt_yi(tf.get("main_net")) if tf.get("main_net") is not None else "—"
        flow_verdict = "主力净流出" if (tf.get("main_net") or 0) < 0 else "主力净流入"
        detail = ""
        if tf:
            rows = [
                ("超大单", _fmt_yi(tf.get("super_large_net")),
                 "bad" if (tf.get("super_large_net") or 0) < 0 else "good"),
                ("大单", _fmt_yi(tf.get("large_net")),
                 "bad" if (tf.get("large_net") or 0) < 0 else "good"),
                ("中单", _fmt_yi(tf.get("medium_net")),
                 "bad" if (tf.get("medium_net") or 0) < 0 else "good"),
                ("小单", _fmt_yi(tf.get("small_net")),
                 "bad" if (tf.get("small_net") or 0) < 0 else "good"),
            ]
            detail = ('<div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 18px;margin-top:8px">'
                      + "".join(
                          f'<div style="display:flex;justify-content:space-between;font-size:13px">'
                          f'<span style="color:var(--muted)">{lbl}</span>'
                          f'<b style="color:{C[tone2]}">{v}</b></div>'
                          for lbl, v, tone2 in rows) + '</div>')
        parts.append(
            '<div style="padding:12px;background:var(--surface2);border-left:3px solid '
            f'{tone};border-radius:6px;margin-bottom:12px">'
            f'<div style="font-size:15px;font-weight:700;color:var(--text)">{_esc(name)} '
            f'<span style="color:var(--muted);font-size:12px;font-weight:400">{_esc(code)} · {_esc(rank_txt)}</span></div>'
            f'<div style="margin-top:6px;font-size:14px">当日主力资金 <b style="color:{tone};font-size:17px">{main_txt}</b>'
            f'（{flow_verdict}）· 板块涨跌 <b style="color:{C["good"] if (chg or 0) >= 0 else C["bad"]}">{_pct(chg)}</b></div>'
            f'{detail}'
            '<div class="sub" style="margin-top:6px">💰 游资视角：主力（大单+超大单）是方向资金；若主力大幅流出而小单流入，'
            '通常=机构/游资撤退、散户接盘，右侧买入要更谨慎。</div></div>')

    bf = cf.get("board_flow") or {}
    if bf.get("industry") or bf.get("concept"):
        ctx = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:8px">'
        for bt, label in (("industry", "行业板块"), ("concept", "概念板块")):
            per = bf.get(bt, {}).get("today", {})
            top5 = per.get("top5") or []
            matched = per.get("matched") or []
            rows = "".join(
                f'<div style="display:flex;justify-content:space-between;font-size:12px;padding:2px 0">'
                f'<span>{_esc(r.get("name", ""))}</span>'
                f'<b style="color:{C["good"] if (r.get("main_net") or 0) >= 0 else C["bad"]}">{_fmt_yi(r.get("main_net"))}</b></div>'
                for r in top5[:5])
            mrow = ""
            if matched:
                mrow = ('<div class="sub" style="margin-top:4px">本基金板块命中：'
                        + "、".join(f'{_esc(r.get("name", ""))}({_fmt_yi(r.get("main_net"))})'
                                    for r in matched[:4]) + '</div>')
            ctx += (f'<div style="padding:8px;background:var(--surface2);border-radius:6px">'
                    f'<div style="font-size:13px;color:var(--muted);margin-bottom:4px">{label} · 今日主力净流入 TOP5</div>'
                    f'{rows}{mrow}</div>')
        ctx += '</div>'
        parts.append(f'<div style="margin-bottom:12px">{ctx}</div>')

    sf = cf.get("stock_flow") or []
    holds = cf.get("holdings") or []
    if sf:
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;font-size:13px;padding:4px 0;'
            f'border-bottom:1px solid var(--border)">'
            f'<span>{_esc(h.get("name", ""))} <span style="color:var(--muted)">{_esc(h.get("code", ""))}'
            f' · 占净值{h.get("weight")}%</span></span>'
            f'<b style="color:{C["good"] if (h.get("latest", {}).get("main_net") or 0) >= 0 else C["bad"]}">'
            f'{_fmt_yi(h.get("latest", {}).get("main_net"))}</b></div>'
            for h in sf if h.get("latest"))
        parts.append('<div style="margin-bottom:12px">'
                     '<div style="font-size:13px;color:var(--muted);margin-bottom:4px">重仓股 · 主力资金（近1日）</div>'
                     f'{rows}</div>')
    elif holds:
        parts.append('<div class="sub" style="margin-bottom:12px">重仓股资金流接口当前不可达'
                     '（东财 push2 实时域名被风控），已自动降级为板块级资金流。</div>')

    dt = cf.get("dragon_tiger") or {}
    if isinstance(dt, dict) and (dt.get("matched") or dt.get("holdings")):
        rows = dt.get("matched") or dt.get("holdings") or []
        txt = "、".join(f'{_esc(r.get("name", ""))}(净买{_fmt_yi(r.get("net_buy") or r.get("净买额") or 0)})'
                        for r in rows[:6])
        parts.append(f'<div class="sub" style="margin-bottom:12px">📋 龙虎榜：{_esc(txt)}</div>')

    nb = cf.get("northbound") or {}
    latest = nb.get("latest") if isinstance(nb, dict) else None
    if isinstance(latest, dict) and latest.get("hgt_yi") is not None:
        hgt = latest.get("hgt_yi")
        sgt = latest.get("sgt_yi")
        hgt_txt = f'{hgt:+.2f}亿' if isinstance(hgt, (int, float)) and hgt == hgt else "—"
        sgt_txt = f'{sgt:+.2f}亿' if isinstance(sgt, (int, float)) and sgt == sgt else "—"
        parts.append(f'<div class="sub" style="margin-bottom:12px">🧭 北向资金（{_esc(str(latest.get("time", "")))}）：'
                     f'沪股通 {hgt_txt} · 深股通 {sgt_txt}</div>')

    gh = cf.get("global_stock_hint") or {}
    if gh.get("available") and gh.get("hits"):
        names = "、".join(f'{_esc(h.get("name", ""))}' for h in gh["hits"][:5])
        parts.append(f'<div style="padding:10px;background:var(--surface2);border-left:3px solid {C["warn"]};'
                     f'border-radius:6px;font-size:13px">🌏 重仓含港/美股（{names}），'
                     f'建议用 global-stock-data 核验对应标的后写入 agent_analysis.json。</div>')

    body = "".join(parts) if parts else '<div class="sub">资金面数据为空（交易日收盘后数据才完整）。</div>'
    return (f'<div class="card">'
            f'<div class="section-title">💧 资金面验证（a-stock-data · {_esc(cf.get("as_of", ""))}）</div>'
            f'{body}'
            '<div class="sub" style="margin-top:6px">数据源：a-stock-data skill（东财 push2delay 降级）。'
            '板块资金流=主力（超大+大单）口径；非投资建议。</div></div>')


def _vibe_backtest_block(vb: dict | None) -> str:
    """Vibe-Trading 独立引擎回测验证卡片。"""
    if not vb or not vb.get("available"):
        return ""
    metrics = vb.get("metrics") or {}
    if not metrics:
        return ('<div class="card"><div class="section-title">🧪 回测验证（Vibe-Trading）</div>'
                '<div class="sub" style="padding:10px">回测已运行但指标缺失。</div></div>')
    wr = metrics.get("win_rate") or 0
    tone_key = "bad" if wr < 0.4 else ("good" if wr >= 0.55 else None)
    verdict = "偏低" if tone_key == "bad" else ("较好" if tone_key == "good" else "尚可")
    arts = vb.get("artifacts") or {}
    art_txt = ""
    if arts.get("run_card_md"):
        art_txt = (f'<div class="sub" style="margin-top:8px">完整回测卡：'
                   f'<span style="color:var(--accent)">{_esc(str(arts["run_card_md"]))}</span></div>')
    return (
        '<div class="card">'
        '<div class="section-title">🧪 回测验证（Vibe-Trading MCP · 独立日线引擎）</div>'
        '<div class="kpi-row">'
        f'{_kpi_tile("累计收益", _pct(metrics.get("total_return")), "", tone_key)}'
        f'{_kpi_tile("年化", _pct(metrics.get("annual_return")), "", tone_key)}'
        f'{_kpi_tile("最大回撤", _pct(metrics.get("max_drawdown")).replace("+", ""), "", "bad" if (metrics.get("max_drawdown") or 0) < -0.2 else None)}'
        f'{_kpi_tile("胜率", _pct(wr).replace("+", ""), verdict, tone_key)}'
        f'{_kpi_tile("交易笔数", metrics.get("trade_count"), "", None)}'
        '</div>'
        '<div class="kpi-row" style="margin-top:8px">'
        + (f'{_kpi_tile("夏普", f"{metrics.get(chr(115) + chr(104) + chr(97) + chr(114) + chr(112) + chr(101), 0):.2f}", "", None)}' if metrics.get("sharpe") is not None else "")
        + (f'{_kpi_tile("盈亏比", f"{metrics.get("profit_loss_ratio", 0):.2f}", "", None)}' if metrics.get("profit_loss_ratio") is not None else "")
        + (f'{_kpi_tile("基准同期", _pct(metrics.get("benchmark_return")), "", None)}' if metrics.get("benchmark_return") is not None else "")
        + (f'{_kpi_tile("超额", _pct(metrics.get("excess_return")), "", None)}' if metrics.get("excess_return") is not None else "")
        + '</div>'
        '<div style="margin-top:10px;padding:10px;background:var(--surface2);border-left:3px solid '
        f'{C["warn"]};border-radius:6px;font-size:13px">'
        '⚠️ 口径说明：这是 Vibe-Trading <b>日线版</b>独立引擎按同一右侧纪律'
        '（MA20/60 结构 + 移动止盈/止损位）自动生成的交叉验证，与上方周线主回测的<b>口径、交易频率不同</b>，'
        '不能直接对比数值，只用于确认"右侧纪律在该基金上长期是否为正期望"。'
        '</div>'
        f'{art_txt}</div>')



def _sector_block(sector: dict | None) -> str:
    """板块共振信号灯详情块。sector 来自 sector_resonance.compute_resonance。"""
    if not sector or not sector.get("available"):
        light = (sector or {}).get("light", "⚪")
        label = (sector or {}).get("label", "板块未接入")
        return f'<div class="sector" style="font-size:14px">{light} {_esc(label)}</div>'
    sr = sector.get("sector_returns_pct", {}) or {}
    sid = sector.get("sector_id", {}) or {}
    light = sector.get("light", "⚪")
    color = {"🟢": C["good"], "🟡": C["warn"], "🔴": C["bad"]}.get(light, C["muted"])
    return f'''
    <div class="sector-detail" style="text-align:center;padding:14px">
      <div style="font-size:22px;margin-bottom:6px">{light}
        <span style="color:{color};font-size:18px;font-weight:700">{_esc(sector['label'])}</span>
      </div>
      <div style="color:var(--text);font-size:14px;margin-bottom:10px">{_esc(sector.get('advice', ''))}</div>
      <div style="color:var(--muted);font-size:12px;line-height:1.7">
        主板块 <b style="color:var(--text)">{_esc(sid.get('main_sector', '—'))}</b> ·
        板块趋势 <b style="color:{color}">{_esc(sector['sector_regime'])}</b>（{_esc(sector.get('sector_alignment', ''))}）·
        指数 {_esc(sector.get('index_symbol', ''))}<br>
        板块收益 1m {_esc(sr.get('1m'))}% / 3m {_esc(sr.get('3m'))}% / 1y {_esc(sr.get('1y'))}% ·
        基金趋势 {_esc(sector.get('fund_regime', ''))}
      </div>
    </div>'''


def _sector_news_block(news: dict | None) -> str:
    """板块消息面卡片（利好/利空双栏 + 总结）。无消息返回空串。"""
    if not news:
        return ""
    has_evidence = bool(news.get("bullish") or news.get("bearish") or news.get("sources"))
    if not has_evidence and news.get("evidence_status") != "unavailable":
        return ""
    bull = "".join(f"<li>{_esc(b)}</li>" for b in (news.get("bullish") or []))
    bear = "".join(f"<li>{_esc(b)}</li>" for b in (news.get("bearish") or []))
    evidence_grid = ""
    if news.get("bullish") or news.get("bearish"):
        evidence_grid = f'''
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div style="background:var(--surface2);border-radius:8px;padding:12px;border-top:3px solid {C['good']}">
      <div style="color:{C['good']};font-weight:600;margin-bottom:6px">🔼 利好</div>
      <ul style="margin:0;padding-left:18px;font-size:12px;line-height:1.7">{bull}</ul>
    </div>
    <div style="background:var(--surface2);border-radius:8px;padding:12px;border-top:3px solid {C['bad']}">
      <div style="color:{C['bad']};font-weight:600;margin-bottom:6px">🔽 利空</div>
      <ul style="margin:0;padding-left:18px;font-size:12px;line-height:1.7">{bear}</ul>
    </div>
  </div>'''
    sources = ""
    if news.get("sources"):
        items = "".join(
            f'<li><a href="{_esc(source["url"])}" target="_blank" rel="noopener noreferrer" '
            f'style="color:{C["accent"]}">{_esc(source["title"])}</a> · '
            f'{_esc(source["date"])} · {_esc(source["stance"])}<br>'
            f'<span style="color:var(--muted)">{_esc(source["summary"])}</span></li>'
            for source in news["sources"]
        )
        sources = (f'<div style="margin-top:12px"><div style="font-size:12px;font-weight:600;'
                   f'margin-bottom:6px">来源</div><ul style="margin:0;padding-left:18px;'
                   f'font-size:12px;line-height:1.7">{items}</ul></div>')
    summary = ""
    if news.get("summary"):
        summary = (f'<div style="margin-top:12px;padding:12px;background:var(--surface2);'
                   f'border-left:3px solid {C["accent"]};border-radius:6px;font-size:13px;line-height:1.6">'
                   f'💡 {_esc(news["summary"])}</div>')
    return f'''
<div class="card">
  <div class="section-title">📰 板块消息面（{_esc(news.get('sector', '板块'))} · 截至 {_esc(news.get('as_of', ''))}）</div>
  {evidence_grid}
  {sources}
  {summary}
</div>'''


# ---------------------------- 主渲染 ----------------------------

def render_html(decision: dict, metrics: dict, signals: dict, nav: pd.DataFrame,
                fund_code: str, fund_name: str = "", sector: dict | None = None) -> str:
    weekly = to_weekly(nav)
    chart = _nav_chart_svg(weekly, signals)
    lv = signals["levels"]
    regime = signals["trend"]["regime"]
    regime_color = {"上升": C["good"], "下降": C["bad"]}.get(regime, C["warn"])
    _act = decision["action"]
    action_color = (C["bad"] if any(k in _act for k in ("不进场", "观望", "假突破", "不加仓", "等待"))
                    else (C["good"] if any(k in _act for k in ("加仓", "建仓", "试探", "关注")) else C["warn"]))
    view = decision.get("view", "empty")
    view_badge = "🧍 空仓视角" if view == "empty" else "💼 持仓视角"

    name_part = f" · {_esc(fund_name)}" if fund_name else ""
    deep = "⚠️ 深度回撤" if decision.get("deep_drawdown") else ""

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>右侧作战卡 · {fund_code}</title>
<style>
  :root {{ --bg:{C['bg']}; --surface:{C['surface']}; --surface2:{C['surface2']}; --border:{C['border']};
           --text:{C['text']}; --muted:{C['muted']}; --accent:{C['accent']}; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--text); font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
          line-height:1.55; }}
  .wrap {{ max-width:1060px; margin:0 auto; padding:18px 16px 64px; }}
  .card {{ background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:18px; margin-bottom:14px; }}
  h1 {{ font-size:19px; font-weight:700; }}
  .sub {{ color:var(--muted); font-size:13px; margin-top:4px; }}
  .head-row {{ display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px; }}
  .chips {{ display:flex; gap:8px; flex-wrap:wrap; }}
  .chip {{ display:inline-block; padding:4px 11px; border-radius:999px; font-size:12px; font-weight:600; }}
  .view-badge {{ background:var(--accent)22; color:var(--accent); }}
  .hero {{ text-align:center; padding:26px 18px; border:1px solid {action_color}55; }}
  .hero-label {{ font-size:12px; color:var(--muted); letter-spacing:1px; text-transform:uppercase; }}
  .hero-action {{ font-size:28px; font-weight:800; margin:10px 0 6px; }}
  .hero-pos {{ display:inline-block; padding:4px 16px; border-radius:999px; background:var(--surface2);
               border:1px solid {action_color}66; color:{action_color}; font-size:14px; font-weight:700; margin:4px 0 12px; }}
  .hero-rationale {{ color:var(--muted); font-size:13px; max-width:760px; margin:0 auto; line-height:1.75; }}
  .section-title {{ font-size:13px; color:var(--muted); letter-spacing:0.5px; margin-bottom:12px; font-weight:700;
                    display:flex; align-items:center; gap:6px; }}
  .section-title::before {{ content:""; width:4px; height:14px; border-radius:2px; background:var(--accent); display:inline-block; }}
  .verdict-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }}
  .verdict-item {{ background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:10px 12px;
                    display:flex; flex-direction:column; gap:2px; }}
  .v-dot {{ font-size:16px; font-weight:800; }}
  .v-label {{ font-size:11px; color:var(--muted); }}
  .v-value {{ font-size:14px; font-weight:700; }}
  .v-note {{ font-size:10px; color:var(--muted); }}
  .gauge-wrap {{ padding:6px 4px 2px; }}
  .gauge {{ position:relative; height:54px; }}
  .g-track {{ position:absolute; left:0; right:0; top:6px; height:6px; border-radius:3px;
               background:linear-gradient(90deg,{C['bad']}44,{C['warn']}55,{C['accent']}66); }}
  .g-mark {{ position:absolute; top:0; transform:translateX(-50%); text-align:center; font-size:10px;
             white-space:nowrap; }}
  .g-mark.cur {{ top:-4px; font-size:12px; font-weight:800; padding-left:6px; }}
  .g-dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:3px; }}
  .g-range {{ display:flex; justify-content:space-between; font-size:10px; color:var(--muted); margin-top:2px; }}
  .level-group {{ margin-bottom:16px; }}
  .level-group-head {{ display:flex; align-items:baseline; gap:8px; margin:12px 0 10px; font-weight:700; font-size:14px; }}
  .level-group-hint {{ font-size:11px; color:var(--muted); font-weight:400; }}
  .levels-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:10px; }}
  .level-card {{ background:var(--surface2); border-radius:10px; padding:12px 14px; }}
  .level-head {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }}
  .level-icon {{ font-size:15px; }}
  .level-label {{ font-size:12px; color:var(--muted); }}
  .status-chip {{ margin-left:auto; padding:2px 9px; border-radius:999px; font-size:11px; font-weight:700;
                   white-space:nowrap; }}
  .level-price-row {{ display:flex; align-items:baseline; gap:10px; margin-bottom:6px; }}
  .level-price {{ font-size:24px; font-weight:800; letter-spacing:0.5px; }}
  .level-cut {{ font-size:11px; color:var(--muted); background:var(--surface); border:1px solid var(--border);
                 padding:1px 8px; border-radius:999px; }}
  .level-trigger {{ font-size:11px; color:var(--muted); line-height:1.55; }}
  .exec-rule {{ background:var(--surface2); border:1px dashed {C['bad']}66; border-radius:8px; padding:10px 12px;
                font-size:12px; color:var(--text); line-height:1.7; margin-bottom:10px; }}
  .kpi-row {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(112px,1fr)); gap:10px; }}
  .kpi {{ background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:12px; text-align:center; }}
  .kpi-label {{ font-size:11px; color:var(--muted); }}
  .kpi-value {{ font-size:19px; font-weight:700; margin:4px 0; }}
  .kpi-sub {{ font-size:10px; color:var(--muted); }}
  .chart {{ width:100%; height:auto; display:block; background:var(--surface2); border-radius:8px; }}
  .tooltip {{ position:absolute; pointer-events:none; background:var(--surface2); border:1px solid var(--border);
              padding:6px 10px; border-radius:6px; font-size:12px; opacity:0; transition:opacity 0.1s;
              transform:translateY(-50%); white-space:nowrap; }}
  .legend {{ display:flex; gap:16px; justify-content:center; margin-top:8px; font-size:11px; color:var(--muted); flex-wrap:wrap; }}
  .legend span {{ display:inline-flex; align-items:center; gap:4px; }}
  .swatch {{ width:14px; height:2px; display:inline-block; }}
  .c-title {{ font-size:12px; color:var(--muted); margin:14px 0 8px; font-weight:600; }}
  .c-bars {{ display:flex; flex-direction:column; gap:8px; }}
  .c-bar-row {{ display:grid; grid-template-columns:86px 1fr 90px; align-items:center; gap:10px; }}
  .c-bar-label {{ font-size:12px; color:var(--muted); text-align:right; }}
  .c-bar-track {{ background:var(--surface2); border-radius:4px; height:14px; overflow:hidden; }}
  .c-bar-fill {{ height:100%; border-radius:4px; }}
  .c-bar-val {{ font-size:12px; font-weight:700; }}
  .sector {{ text-align:center; padding:14px; color:var(--muted); font-size:13px; }}
  .disclaimer {{ color:var(--muted); font-size:11px; text-align:center; padding:16px; line-height:1.7; }}
  .gate-note {{ display:flex; flex-wrap:wrap; gap:8px; justify-content:center; }}
  .gate-note span {{ font-size:11px; color:var(--muted); background:var(--surface2); border:1px solid var(--border);
                      padding:4px 10px; border-radius:999px; }}
  @media(max-width:640px){{
    .levels-grid,.kpi-row,.verdict-grid {{ grid-template-columns:1fr 1fr; }}
    .hero-action {{ font-size:22px; }}
    .c-bar-row {{ grid-template-columns:72px 1fr 78px; gap:6px; }}
    .wrap {{ padding:12px 10px 48px; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <div class="card">
    <div class="head-row">
      <div>
        <h1>右侧作战卡 · {_esc(fund_code)}{name_part}</h1>
        <div class="sub">当前净值 <b style="color:var(--text)">{lv['current']}</b> · {metrics['latest_date']} · {metrics['data_points']} 个交易日</div>
      </div>
      <div class="chips">
        <span class="chip" style="background:{regime_color}26;color:{regime_color}">趋势：{regime}</span>
        <span class="chip" style="background:var(--surface2);color:var(--muted)">{signals['trend']['alignment']}</span>
        <span class="chip view-badge">{view_badge}</span>
        {f'<span class="chip" style="background:{C["warn"]}26;color:{C["warn"]}">{deep}</span>' if deep else ''}
      </div>
    </div>
  </div>

  <div class="card hero">
    <div class="hero-label">▶ 结论 · 该不该动手</div>
    <div class="hero-action" style="color:{action_color}">{_esc(decision['action'])}</div>
    <div class="hero-pos">建议仓位 {_esc(decision['position'])}</div>
    <div class="hero-rationale">{_esc(decision['rationale'])}</div>
  </div>

  <div class="card">
    <div class="section-title">🧭 判定清单（为什么是这个结论）</div>
    {_verdict_strip(signals, sector, decision)}
  </div>

  <div class="card">
    <div class="section-title">📍 当前价格定位（相对关键位）</div>
    {_price_gauge(signals, decision)}
  </div>

  <div class="card">
    <div class="section-title">🎯 关键净值位（{view_badge}）</div>
    {_levels_groups(decision)}
  </div>

  <div class="card">
    <div class="section-title">📈 净值走势（周线，近 3 年）</div>
    <div style="position:relative">{chart}</div>
    <div class="legend">
      <span><span class="swatch" style="background:{C['accent']}"></span>单位净值</span>
      <span><span class="swatch" style="background:{C['ma_fast']};border-top:1px dashed {C['ma_fast']}"></span>MA20周</span>
      <span><span class="swatch" style="background:{C['ma_slow']}"></span>MA60周</span>
    </div>
  </div>

  <div class="card">
    <div class="section-title">📊 风险收益指标</div>
    {_kpi_row(metrics, signals)}
  </div>

  {_backtest_block(decision.get("backtest"))}

  {_vibe_backtest_block(decision.get("vibe_backtest"))}

  {_valuation_block(decision.get("valuation"))}

  <div class="card">
    <div class="section-title">🟢🟡🔴 板块共振信号</div>
    {_sector_block(sector)}
  </div>

  {_capital_flow_block(sector)}

  {_sector_news_block(decision.get("sector_news"))}

  <div class="card">
    <div class="section-title">⚙️ 门控与说明</div>
    <div class="gate-note">
      <span>移动止盈阈值 {decision['trailing_stop_pct']*100:.0f}%（基准：{'入场后峰值' if view == 'holding' else '52 周高点参考'}）</span>
      <span>跌破型位需连续 2 日收盘确认</span>
      <span>止损含 1% 缓冲</span>
      <span>ETF 突破需放量（≥1.5x 强 / &lt;1.2x 警惕）</span>
    </div>
  </div>

  <div class="disclaimer">
    ⚠️ 本报告为右侧交易策略框架的机械信号输出，<b>非投资建议</b>。场外基金 T+1、净值滞后，信号仅供决策参考，盈亏自负。<br>
    fund-deep-analysis v0.6 · 数据源 akshare/天天基金 + a-stock-data/Vibe-Trading · {metrics['latest_date']} 生成
  </div>

</div>
</body>
</html>'''
