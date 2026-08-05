"""trend_signals.py — 周线趋势 + 日线辅助信号（右侧交易核心）v0.5

周线为主（20/60 周线判大趋势），日线辅助找精确买点。
输出趋势状态 + 关键信号（更高低点/均线拐头/突破/金叉死叉）+ 决策用关键净值位。

v0.5 修复：
  1. higher_lows 在低点不足 2 个时仍返回已发现的低点（不再返回空数组自相矛盾）
  2. 新增 stop_low（双轨止损参考）：已确认 swing low 与最近 4 周最低点取低者，
     避免"止损位高于最新可见低点"（k=3 确认盲区）
  3. 新增 fast 快速右侧探针（日线辅助）：MA5/MA10 短期结构、距 20 日低点反弹幅度、
     是否创 20 日新高，供"板块先行/放量反弹"加速判断
  4. key_levels 增加 prev_close（前收盘），供跌破型位的双日确认
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
    """返回 swing low 的位置 index（比左右 k 期都低的局部谷底）。

    v0.5：支持平台型底部 —— 允许 arr[i] <= arr[i-1]（左平台），
    且要求 arr[i] < arr[i+1]（严格低于右侧），因此平台只取最后一根，
    避免连续相同最低值（如净值连续两天持平）被漏检。
    """
    arr = price.values
    lows = []
    for i in range(k, len(arr) - k):
        seg = arr[i - k : i + k + 1]
        if arr[i] == seg.min() and arr[i] <= arr[i - 1] and arr[i] < arr[i + 1]:
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

    # regime 判定（主信号）
    bullish = has_fast and has_slow and last_fast > last_slow and last_price > last_fast and fast_slope > 0
    bearish = has_fast and has_slow and last_fast < last_slow and last_price < last_fast and fast_slope < 0
    if bullish:
        regime = "上升"
    elif bearish:
        regime = "下降"
    else:
        regime = "震荡"

    # 连续站上 MA20 周数（趋势确认期，过滤斜率瞬时抖动）
    above_weeks = 0
    if has_fast:
        closes = price.values
        mas = ma_fast.values
        for j in range(len(closes) - 1, -1, -1):
            if pd.notna(mas[j]) and closes[j] > mas[j]:
                above_weeks += 1
            else:
                break

    return {
        "regime": regime,
        "alignment": alignment,
        "ma20w": round(float(last_fast), 4) if has_fast else None,
        "ma60w": round(float(last_slow), 4) if has_slow else None,
        "ma20_slope_up": bool(fast_slope > 0) if pd.notna(fast_slope) else False,
        "recent_cross": cross,
        "above_ma20w_weeks": above_weeks,
    }


def higher_lows(weekly: pd.DataFrame, lookback: int = 30) -> dict:
    """检测最近是否形成更高低点（右侧企稳信号）。

    v0.5：低点不足 2 个时仍返回已发现的低点列表（不返回空数组），
    供止损双轨与 JSON 自洽。
    """
    price = weekly["unit_nav"].iloc[-lookback:].reset_index(drop=True)
    if len(price) < 10:
        return {"higher_lows": False, "recent_lows": []}
    lows = _swing_lows(price, k=3)
    if len(lows) < 2:
        return {
            "higher_lows": False,
            "recent_lows": [round(float(price.iloc[i]), 4) for i in lows],
        }
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


def fast_signal(nav: pd.DataFrame) -> dict:
    """日线快速右侧探针（v0.5 新增）。

    用于"板块先行 / 放量反弹"加速判断：周线主信号确认之前，
    日线短期结构是否已经转多、反弹是否站上关键幅度。
    """
    price = nav["unit_nav"].dropna()
    if len(price) < 25:
        return {"available": False}
    ma5d = price.rolling(5, min_periods=5).mean().iloc[-1]
    ma10d = price.rolling(10, min_periods=10).mean().iloc[-1]
    ma20d = price.rolling(20, min_periods=20).mean().iloc[-1]
    cur = float(price.iloc[-1])

    recent_20 = price.iloc[-21:-1]  # 不含当日
    low_20 = float(recent_20.min())
    high_20 = float(recent_20.max())

    # 距最近 20 日低点的反弹幅度
    pct_off_low = round((cur / low_20 - 1) * 100, 2) if low_20 > 0 else None
    # 距 20 日高点
    pct_to_high20 = round((cur / high_20 - 1) * 100, 2) if high_20 > 0 else None

    # 距最近一次 20 日低点的天数（最近21日窗口内最小值最后出现位置）
    win = price.iloc[-21:]
    days_since_low = int(len(win) - 1 - win.values[::-1].argmin())

    return {
        "available": True,
        "daily_ma_align": bool(pd.notna(ma5d) and pd.notna(ma10d) and ma5d > ma10d),
        "price_above_ma20d": bool(pd.notna(ma20d) and cur > ma20d),
        "ma5d": round(float(ma5d), 4) if pd.notna(ma5d) else None,
        "ma10d": round(float(ma10d), 4) if pd.notna(ma10d) else None,
        "ma20d": round(float(ma20d), 4) if pd.notna(ma20d) else None,
        "pct_off_low_20d": pct_off_low,
        "pct_to_high_20d": pct_to_high20,
        "new_20d_high": bool(cur >= high_20),
        "days_since_low_20d": days_since_low,
        "bounce_1m_pct": round((cur / float(price.iloc[-22]) - 1) * 100, 2) if len(price) >= 22 else None,
    }


# ---------------------------- 关键净值位（决策用） ----------------------------

def key_levels(nav: pd.DataFrame, weekly: pd.DataFrame) -> dict:
    """汇总右侧决策需要的关键净值位。v0.5：新增 stop_low / prev_close。"""
    price_d = nav["unit_nav"].dropna()
    price_w = weekly["unit_nav"]
    ma_fast = _ma(price_w, FAST_WEEKS)
    ma_slow = _ma(price_w, SLOW_WEEKS)
    ma5d = price_d.rolling(5, min_periods=5).mean()
    ma10d = price_d.rolling(10, min_periods=10).mean()

    # 近 26 周（半年）周线 swing low 作为止损参考前低
    recent_w = price_w.iloc[-26:].reset_index(drop=True)
    lows = _swing_lows(recent_w, k=3)
    confirmed_low = round(float(recent_w.iloc[lows[-1]]), 4) if lows else None

    # 最近 4 周最低收盘（含尚未被 swing 确认的最新低点，k=3 盲区兜底）
    pending_low = round(float(price_w.iloc[-4:].min()), 4) if len(price_w) >= 4 else None

    # 双轨止损：取两者更低者 —— 止损位永远不高于最新可见低点
    if confirmed_low is not None and pending_low is not None:
        stop_low = round(min(confirmed_low, pending_low), 4)
    else:
        stop_low = confirmed_low if confirmed_low is not None else pending_low

    # 阶段高点（近 52 周周线最高）= 移动止盈参考基准（空仓视角）
    stage_window = min(52, len(price_w))
    stage_high = round(float(price_w.iloc[-stage_window:].max()), 4)

    return {
        "current": round(float(price_d.iloc[-1]), 4),
        "prev_close": round(float(price_d.iloc[-2]), 4) if len(price_d) >= 2 else None,
        "ma5d": round(float(ma5d.iloc[-1]), 4) if pd.notna(ma5d.iloc[-1]) else None,
        "ma10d": round(float(ma10d.iloc[-1]), 4) if pd.notna(ma10d.iloc[-1]) else None,
        "ma20w": round(float(ma_fast.iloc[-1]), 4) if pd.notna(ma_fast.iloc[-1]) else None,
        "ma60w": round(float(ma_slow.iloc[-1]), 4) if pd.notna(ma_slow.iloc[-1]) else None,
        "recent_swing_low": confirmed_low,      # 已确认 swing low（参考）
        "pending_low": pending_low,             # 最新可见低点（未确认）
        "stop_low": stop_low,                   # 双轨止损位（决策用）
        "stage_high_52w": stage_high,
        "pct_below_stage_high": round(float(price_d.iloc[-1] / stage_high - 1) * 100, 2),
    }


def compute_signals(nav: pd.DataFrame) -> dict:
    """汇总所有趋势信号 → dict（供 right_side_engine 决策）。v0.5：+ fast。"""
    weekly = to_weekly(nav)
    return {
        "weekly_bars": int(len(weekly)),
        "trend": detect_trend(weekly),
        "structure": higher_lows(weekly),
        "breakout_daily": breakout(nav),
        "fast": fast_signal(nav),
        "levels": key_levels(nav, weekly),
    }


if __name__ == "__main__":
    import json

    import akshare as ak

    df = ak.fund_open_fund_info_em(symbol="161725", period="近期")
    df = df.rename(columns={"净值日期": "date", "单位净值": "unit_nav", "日增长率": "daily_return"})
    df["date"] = pd.to_datetime(df["date"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    print(json.dumps(compute_signals(df), ensure_ascii=False, indent=2))

