"""sector_resonance.py — 板块走势对比 + 共振信号灯

拉取主板块指数（新浪源，绕开 push2 限制），算板块 regime，
与基金 regime 叠加 → 共振信号灯（右侧放大器）。

共振逻辑（见 assets/right-side-rules.md）：
  基金右侧 + 板块右侧 = 🟢 强确认重仓
  基金右侧 + 板块震荡 = 🟡 轻仓试探
  基金右侧 + 板块走弱 = 🔴 警惕假突破
  板块见顶（转下降）   = 止盈预警（领先信号）
"""
from __future__ import annotations

import os

os.environ["NO_PROXY"] = "*"  # bypass 系统代理，新浪源也走直连更稳

import json

import pandas as pd

from trend_signals import to_weekly, detect_trend


def fetch_sector_index(symbol: str) -> pd.DataFrame | None:
    """新浪源拿板块指数日收盘。失败返回 None（调用方降级）。"""
    try:
        import akshare as ak

        df = ak.stock_zh_index_daily(symbol=symbol)
        if df is None or not len(df):
            return None
        df = df.rename(columns={"close": "unit_nav"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
        df = df.dropna(subset=["date", "unit_nav"]).sort_values("date").reset_index(drop=True)
        return df[["date", "unit_nav"]]
    except Exception:
        return None


def _period_returns(s: pd.Series) -> dict:
    out = {}
    for label, days in [("1m", 22), ("3m", 64), ("1y", 253)]:
        out[label] = round(float(s.iloc[-1] / s.iloc[-days - 1] - 1) * 100, 2) if len(s) > days else None
    return out


def compute_resonance(fund_signals: dict, index_symbols: list[str], fund_code: str = "") -> dict:
    """基金 regime + 板块 regime → 共振信号灯。

    Args:
        fund_signals: trend_signals.compute_signals 的输出
        index_symbols: 板块指数候选 symbol 列表（逐个尝试直到拿到）
    """
    fund_regime = fund_signals["trend"]["regime"]

    sector_df = None
    used_symbol = None
    for sym in index_symbols:
        sector_df = fetch_sector_index(sym)
        if sector_df is not None and len(sector_df) > 60:
            used_symbol = sym
            break

    if sector_df is None or len(sector_df) < 60:
        return {
            "available": False,
            "fund_code": fund_code,
            "fund_regime": fund_regime,
            "sector_regime": None,
            "light": "⚪",
            "label": "板块指数未获取",
            "advice": "（指数代码未验证或网络不可达，跳过板块共振）",
        }

    sector_weekly = to_weekly(sector_df)
    sector_trend = detect_trend(sector_weekly)
    sector_regime = sector_trend["regime"]
    sector_returns = _period_returns(sector_df["unit_nav"])

    # 共振信号灯
    if fund_regime == "上升":
        if sector_regime == "上升":
            light, label, advice = "🟢", "强确认", "基金 + 板块双右侧，可重仓"
        elif sector_regime == "震荡":
            light, label, advice = "🟡", "轻仓试探", "基金右侧但板块震荡，轻仓试探"
        else:
            light, label, advice = "🔴", "警惕假突破", "基金右侧但板块走弱，慎进 / 板块见顶预警"
    elif fund_regime == "震荡":
        if sector_regime == "上升":
            light, label, advice = "🟡", "板块先行", "板块已右侧、基金待启动，关注跟进"
        else:
            light, label, advice = "🟡", "共振观望", "基金 + 板块均未确认右侧"
    else:  # fund 下降
        if sector_regime == "上升":
            light, label, advice = "🟡", "基金落后板块", "板块右侧但基金未启动，留意选股/风格"
        else:
            light, label, advice = "🔴", "同步下跌", "基金 + 板块同跌，纪律观望"

    return {
        "available": True,
        "fund_code": fund_code,
        "index_symbol": used_symbol,
        "fund_regime": fund_regime,
        "sector_regime": sector_regime,
        "sector_alignment": sector_trend["alignment"],
        "light": light,
        "label": label,
        "advice": advice,
        "sector_returns_pct": sector_returns,
    }


if __name__ == "__main__":
    import akshare as ak
    from sector_exposure import identify_sector

    os.environ["NO_PROXY"] = "*"
    h = ak.fund_portfolio_hold_em(symbol="161725", date="2024")
    sec = identify_sector("招商中证白酒", h)
    print("板块识别:", sec["main_sector"], sec["index_symbols"], "|", sec["identification"])

    fund_signals = {"trend": {"regime": "下降", "alignment": "空头排列"}}
    res = compute_resonance(fund_signals, sec["index_symbols"], "161725")
    print(json.dumps(res, ensure_ascii=False, indent=2))
