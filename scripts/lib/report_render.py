"""report_render.py — 右侧作战卡 HTML 报告渲染器

把作战卡渲染成自包含的 Bloomberg 深色风格 HTML（单文件，无外部依赖，可手机分享）。
遵守 dataviz skill 原则：单系列主线 + 中性灰参考线、状态色配图标+标签不单靠颜色、
数字用文字色、一根轴、净值曲线带 hover tooltip。

配色用业界验证 CVD 友好的深色方案（GitHub Dark / Bloomberg 风）。
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


# ---------------------------- 净值位卡片 / KPI ----------------------------

def _level_card(level: dict) -> str:
    status = level.get("status", "")
    color = {"建议": C["good"], "可轻仓试探": C["good"], "暂不建议": C["warn"],
             "不建议": C["bad"], "已持仓·不重复建仓": C["muted"],
             "若持有·触发即撤": C["muted"], "⚠️ 已触发": C["bad"],
             "—": C["muted"]}.get(status, C["accent"])
    price_txt = f"{level['price']}" if level.get("price") is not None else "—"
    return f'''
    <div class="level-card" style="border-color:{color}33">
      <div class="level-head"><span class="level-icon">{level['icon']}</span>
        <span class="level-label">{_esc(level['label'])}</span>
        <span class="level-status" style="color:{color}">{_esc(status)}</span></div>
      <div class="level-price" style="color:{color}">{_esc(price_txt)}</div>
      <div class="level-cut">{_esc(level.get('cut', ''))}</div>
      <div class="level-trigger">{_esc(level.get('reason', ''))}</div>
    </div>'''


def _levels_grid(decision: dict) -> str:
    cards = [_level_card(lv) for lv in decision.get("levels", [])]
    return f'<div class="levels-grid">{"".join(cards)}</div>'


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


# ---------------------------- 主渲染 ----------------------------

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


def _backtest_block(bt: dict | None) -> str:
    """历史回测卡片：信号在该基金的历史胜率/收益。"""
    if not bt or not bt.get("n_trades") or bt.get("win_rate") is None:
        return ""
    wr = bt["win_rate"]
    tone_key = "bad" if wr < 40 else ("good" if wr >= 55 else None)
    verdict = "偏低" if wr < 40 else ("尚可" if wr < 55 else "较好")
    bench_tiles = ""
    if bt.get("benchmark_return_pct") is not None:
        beat = bt["total_return_pct"] > bt["benchmark_return_pct"]
        bench_tiles = (
            _kpi_tile("同期买入持有", f"{bt['benchmark_return_pct']}%", "", "bad" if not beat else "good")
            + _kpi_tile("策略最大回撤", f"{bt['strategy_max_drawdown_pct']}%", "", None)
            + _kpi_tile("基准最大回撤", f"{bt['benchmark_max_drawdown_pct']}%", "", None)
            + _kpi_tile("平均持仓", f"{bt['avg_hold_weeks']}周", "", None)
        )
    return f'''
<div class="card">
  <div class="section-title">📉 历史回测（信号在此基金的历史表现 · 含手续费）</div>
  <div class="kpi-row">
    {_kpi_tile("交易笔数", bt['n_trades'], "", None)}
    {_kpi_tile("胜率", f"{wr}%", verdict, tone_key)}
    {_kpi_tile("平均单笔", f"{bt['avg_return_pct']}%", "", "bad" if bt['avg_return_pct'] < 0 else "good")}
    {_kpi_tile("累计", f"{bt['total_return_pct']}%", "", tone_key)}
    {bench_tiles}
  </div>
  <div class="sub" style="margin-top:10px">单笔最大盈亏：+{bt['max_gain_pct']}% / {bt['max_loss_pct']}%</div>
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


def render_html(decision: dict, metrics: dict, signals: dict, nav: pd.DataFrame,
                fund_code: str, fund_name: str = "", sector: dict | None = None) -> str:
    weekly = to_weekly(nav)
    chart = _nav_chart_svg(weekly, signals)
    levels = _levels_grid(decision)
    kpi = _kpi_row(metrics, signals)
    lv = signals["levels"]
    regime = signals["trend"]["regime"]
    regime_color = {"上升": C["good"], "下降": C["bad"]}.get(regime, C["warn"])
    _act = decision["action"]
    action_color = (C["bad"] if any(k in _act for k in ("不进场", "观望", "假突破", "不加仓", "等待"))
                    else (C["good"] if any(k in _act for k in ("加仓", "建仓", "试探", "关注")) else C["warn"]))

    name_part = f" · {_esc(fund_name)}" if fund_name else ""
    deep = " ⚠️ 深度回撤" if decision.get("deep_drawdown") else ""

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
          line-height:1.5; padding:20px; max-width:980px; margin:0 auto; }}
  .card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:18px; margin-bottom:16px; }}
  h1 {{ font-size:20px; font-weight:600; }}
  .sub {{ color:var(--muted); font-size:13px; margin-top:4px; }}
  .head-row {{ display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px; }}
  .chip {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:600; }}
  .hero {{ text-align:center; padding:24px 18px; }}
  .hero-action {{ font-size:26px; font-weight:700; margin:8px 0; }}
  .hero-pos {{ display:inline-block; padding:4px 16px; border-radius:8px; background:var(--surface2);
               border:1px solid var(--border); font-size:15px; margin:6px 0 12px; }}
  .hero-rationale {{ color:var(--muted); font-size:13px; max-width:640px; margin:0 auto; }}
  .section-title {{ font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px;
                    margin-bottom:12px; font-weight:600; }}
  .chart {{ width:100%; height:auto; display:block; background:var(--surface2); border-radius:8px; }}
  .tooltip {{ position:absolute; pointer-events:none; background:var(--surface2); border:1px solid var(--border);
              padding:6px 10px; border-radius:6px; font-size:12px; opacity:0; transition:opacity 0.1s;
              transform:translateY(-50%); white-space:nowrap; }}
  .levels-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px; }}
  .level-card {{ background:var(--surface2); border:1px solid; border-radius:10px; padding:12px; }}
  .level-head {{ display:flex; align-items:center; gap:6px; margin-bottom:6px; }}
  .level-icon {{ font-size:16px; }}
  .level-label {{ font-size:12px; color:var(--muted); }}
  .level-status {{ margin-left:auto; font-size:11px; font-weight:600; }}
  .level-price {{ font-size:20px; font-weight:700; }}
  .level-cut {{ font-size:11px; color:var(--muted); margin-top:2px; }}
  .level-trigger {{ font-size:10px; color:var(--muted); margin-top:6px; line-height:1.3; }}
  .kpi-row {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(110px,1fr)); gap:10px; }}
  .kpi {{ background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:12px; text-align:center; }}
  .kpi-label {{ font-size:11px; color:var(--muted); }}
  .kpi-value {{ font-size:20px; font-weight:700; margin:4px 0; }}
  .kpi-sub {{ font-size:10px; color:var(--muted); }}
  .sector {{ text-align:center; padding:14px; color:var(--muted); font-size:13px; }}
  .disclaimer {{ color:var(--muted); font-size:11px; text-align:center; padding:16px; line-height:1.6; }}
  .legend {{ display:flex; gap:16px; justify-content:center; margin-top:8px; font-size:11px; color:var(--muted); flex-wrap:wrap; }}
  .legend span {{ display:inline-flex; align-items:center; gap:4px; }}
  .swatch {{ width:14px; height:2px; display:inline-block; }}
  @media(max-width:560px){{ .levels-grid,.kpi-row {{ grid-template-columns:repeat(2,1fr); }} body{{ padding:12px; }} }}
</style>
</head>
<body>

<div class="card">
  <div class="head-row">
    <div>
      <h1>右侧作战卡 · {_esc(fund_code)}{name_part}</h1>
      <div class="sub">当前净值 <b style="color:var(--text)">{lv['current']}</b> · {metrics['latest_date']} · {metrics['data_points']} 个交易日</div>
    </div>
    <div>
      <span class="chip" style="background:{regime_color}22;color:{regime_color}">趋势：{regime}</span>
      <span class="chip" style="background:var(--surface2);color:var(--muted)">{signals['trend']['alignment']}</span>
      <span class="chip" style="background:var(--surface2);color:var(--muted)">{'🧍 空仓视角' if decision.get('view','empty')=='empty' else '💼 持仓视角'}</span>
      <span class="chip" style="background:{C['warn']}22;color:{C['warn']}">{deep.strip()}</span>
    </div>
  </div>
</div>

<div class="card hero">
  <div class="section-title">操作建议</div>
  <div class="hero-action" style="color:{action_color}">{_esc(decision['action'])}</div>
  <div class="hero-pos">建议仓位 {_esc(decision['position'])}</div>
  <div class="hero-rationale">{_esc(decision['rationale'])}</div>
</div>

<div class="card">
  <div class="section-title">净值走势（周线，近 3 年）</div>
  <div style="position:relative">{chart}</div>
  <div class="legend">
    <span><span class="swatch" style="background:{C['accent']}"></span>单位净值</span>
    <span><span class="swatch" style="background:{C['ma_fast']};border-top:1px dashed {C['ma_fast']}"></span>MA20周</span>
    <span><span class="swatch" style="background:{C['ma_slow']}"></span>MA60周</span>
  </div>
</div>

<div class="card">
  <div class="section-title">关键净值位（建仓 / 加仓 / 止盈 / 止损）</div>
  {levels}
</div>

<div class="card">
  <div class="section-title">风险收益指标</div>
  {kpi}
</div>

{_backtest_block(decision.get("backtest"))}

{_valuation_block(decision.get("valuation"))}

<div class="card">
  <div class="section-title">板块共振信号</div>
  {_sector_block(sector)}
</div>

{_sector_news_block(decision.get("sector_news"))}

<div class="disclaimer">
⚠️ 本报告为右侧交易策略框架的机械信号输出，<b>非投资建议</b>。场外基金 T+1、净值滞后，信号仅供决策参考，盈亏自负。<br>
fund-deep-analysis v0.1 · 数据源 akshare/天天基金 · {metrics['latest_date']} 生成
</div>

</body>
</html>'''
