"""trend_signals.py — 周线趋势 + 日线辅助信号（右侧交易核心）

周线为主（20/60 周线判大趋势），日线辅助找精确买点。
输出趋势状态 + 关键信号（更高低点/均线拐头/突破/金叉死叉）+ 决策用关键净值位。

右侧铁律：不抄底不猜顶，趋势确认才动手。本模块只判定"趋势是什么"，
"该不该动手"由 right_side_engine.py 决策。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAST_WEEKS = 20   # 主趋势均线（周）
SLOW_WEEKS = 60   # 长期趋势均线（周）


# ---------------------------- 基础工具 ----------------------------

def to_weekly(nav: pd.DataFrame) -> pd.DataFrame:
    """日净值 → 周线（按 ISO 周聚合，取周内最后一个交易日的净值）。"""
    s = nav[["date", "unit_nav"]].dropna().copy()
    s["week"] = s["date"].dt.to_period("W")
    weekly = s.groupby("week").last().reset_index()
    return weekly[["date", "unit_nav"]]


def _ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(window=n, min_periods=n).mean()


def _swing_lows(price: pd.Series, k: int = 3) -> list[int]:
    """返回 swing low 的位置 index（比左右 k 期都低的局部谷底）。"""
    arr = price.values
    lows = []
    for i in range(k, len(arr) - k):
        seg = arr[i - k : i + k + 1]
        if arr[i] == seg.min() and arr[i] < arr[i - 1] and arr[i] < arr[i + 1]:
            lows.append(i)
    return lows


# ---------------------------- 趋势判定 ----------------------------

def detect_trend(weekly: pd.DataFrame, fast: int = FAST_WEEKS, slow: int = SLOW_WEEKS) -> dict:
    """周线趋势状态 + 均线排列 + 金叉/死叉。"""
    price = weekly["unit_nav"]
    ma_fast = _ma(price, fast)
    ma_slow = _ma(price, slow)

    last_price = float(price.iloc[-1])
    last_fast = ma_fast.iloc[-1]
    last_slow = ma_slow.iloc[-1]
    fast_slope = ma_fast.diff().tail(3).mean()  # 近 3 周均线斜率

    has_fast = pd.notna(last_fast)
    has_slow = pd.notna(last_slow)

    if has_fast and has_slow:
        if last_fast > last_slow:
            alignment = "多头排列"
        elif last_fast < last_slow:
            alignment = "空头排列"
        else:
            alignment = "均线缠绕"
    else:
        alignment = "数据不足"

    # 金叉/死叉（最近 4 周内发生）
    cross = "无"
    if has_fast and has_slow:
        diff = (ma_fast - ma_slow).tail(5).dropna()
        if len(diff) >= 2:
            if diff.iloc[-2] < 0 and diff.iloc[-1] > 0:
                cross = "金叉(近)"
            elif diff.iloc[-2] > 0 and diff.iloc[-1] < 0:
                cross = "死叉(近)"

    # regime 判定
    bullish = has_fast and has_slow and last_fast > last_slow and last_price > last_fast and fast_slope > 0
    bearish = has_fast and has_slow and last_fast < last_slow and last_price < last_fast and fast_slope < 0
    if bullish:
        regime = "上升"
    elif bearish:
        regime = "下降"
    else:
        regime = "震荡"

    return {
        "regime": regime,
        "alignment": alignment,
        "ma20w": round(float(last_fast), 4) if has_fast else None,
        "ma60w": round(float(last_slow), 4) if has_slow else None,
        "ma20_slope_up": bool(fast_slope > 0) if pd.notna(fast_slope) else False,
        "recent_cross": cross,
    }


def higher_lows(weekly: pd.DataFrame, lookback: int = 30) -> dict:
    """检测最近是否形成更高低点（右侧企稳信号）。"""
    price = weekly["unit_nav"].iloc[-lookback:].reset_index(drop=True)
    if len(price) < 10:
        return {"higher_lows": False, "recent_lows": []}
    lows = _swing_lows(price, k=3)
    if len(lows) < 2:
        return {"higher_lows": False, "recent_lows": []}
    a, b = lows[-2], lows[-1]
    higher = price.iloc[b] > price.iloc[a]
    return {
        "higher_lows": bool(higher),
        "recent_lows": [round(float(price.iloc[a]), 4), round(float(price.iloc[b]), 4)],
    }


def breakout(nav: pd.DataFrame, window: int = 60) -> dict:
    """日线辅助：是否突破近 window 日高点（排除当日）。场内 ETF 额外检测放量。"""
    price = nav["unit_nav"].dropna()
    w = min(window, len(price) - 1)
    if w < 5:
        return {"breakout": False, "recent_high": None, "pct_to_high": None, "volume_surge": None}
    recent_high = price.iloc[-w - 1 : -1].max()
    last = price.iloc[-1]
    is_break = bool(last > recent_high)

    # 放量确认（仅场内 ETF 有 volume 字段）：当日量 / 近 20 日均量
    vol_surge = None
    if "volume" in nav.columns:
        vol = nav["volume"].dropna()
        if len(vol) >= 20:
            avg_vol_20 = vol.iloc[-21:-1].mean()
            last_vol = vol.iloc[-1]
            if avg_vol_20 and avg_vol_20 > 0:
                vol_surge = round(float(last_vol / avg_vol_20), 2)

    return {
        "breakout": is_break,
        "recent_high": round(float(recent_high), 4),
        "pct_to_high": round(float(last / recent_high - 1) * 100, 2),
        "volume_surge": vol_surge,  # >1.5 视为放量突破；None=场外基金无量
    }


# ---------------------------- 关键净值位（决策用） ----------------------------

def key_levels(nav: pd.DataFrame, weekly: pd.DataFrame) -> dict:
    """汇总右侧决策需要的关键净值位。"""
    price_d = nav["unit_nav"].dropna()
    price_w = weekly["unit_nav"]
    ma_fast = _ma(price_w, FAST_WEEKS)
    ma_slow = _ma(price_w, SLOW_WEEKS)
    ma5d = price_d.rolling(5, min_periods=5).mean()
    ma10d = price_d.rolling(10, min_periods=10).mean()

    # 近 26 周（半年）周线 swing low 作为止损参考前低
    recent_w = price_w.iloc[-26:].reset_index(drop=True)
    lows = _swing_lows(recent_w, k=3)
    recent_swing_low = round(float(recent_w.iloc[lows[-1]]), 4) if lows else round(float(recent_w.min()), 4)

    # 阶段高点（近 52 周周线最高）= 移动止盈基准
    stage_window = min(52, len(price_w))
    stage_high = round(float(price_w.iloc[-stage_window:].max()), 4)

    return {
        "current": round(float(price_d.iloc[-1]), 4),
        "ma5d": round(float(ma5d.iloc[-1]), 4) if pd.notna(ma5d.iloc[-1]) else None,
        "ma10d": round(float(ma10d.iloc[-1]), 4) if pd.notna(ma10d.iloc[-1]) else None,
        "ma20w": round(float(ma_fast.iloc[-1]), 4) if pd.notna(ma_fast.iloc[-1]) else None,
        "ma60w": round(float(ma_slow.iloc[-1]), 4) if pd.notna(ma_slow.iloc[-1]) else None,
        "recent_swing_low": recent_swing_low,
        "stage_high_52w": stage_high,
        "pct_below_stage_high": round(float(price_d.iloc[-1] / stage_high - 1) * 100, 2),
    }


def compute_signals(nav: pd.DataFrame) -> dict:
    """汇总所有趋势信号 → dict（供 right_side_engine 决策）。"""
    weekly = to_weekly(nav)
    return {
        "weekly_bars": int(len(weekly)),
        "trend": detect_trend(weekly),
        "structure": higher_lows(weekly),
        "breakout_daily": breakout(nav),
        "levels": key_levels(nav, weekly),
    }


if __name__ == "__main__":
    import akshare as ak
    import json

    df = ak.fund_open_fund_info_em(symbol="161725", period="近期")
    df = df.rename(columns={"净值日期": "date", "单位净值": "unit_nav", "日增长率": "daily_return"})
    df["date"] = pd.to_datetime(df["date"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    print(json.dumps(compute_signals(df), ensure_ascii=False, indent=2))
