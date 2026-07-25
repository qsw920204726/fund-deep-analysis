"""risk_metrics.py — 基金风险收益指标

基于日净值（单位净值 unit_nav）序列计算风险调整后收益指标。
所有指标用日级数据计算（年化波动 √252）；趋势判定在 trend_signals.py 用周线。

注：单位净值对含分红的基金会低估真实总回报，累计净值留 v2 补。
    对指数联接/股票型基金（极少分红），单位净值 ≈ 真实走势，足够右侧趋势分析。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252       # 一年交易日数
RISK_FREE = 0.02         # 无风险利率（货币基金/国债近似），可调


def daily_returns(nav: pd.DataFrame) -> pd.Series:
    """日收益率序列（小数）。优先用 daily_return 列（百分比），否则从 unit_nav 推算。"""
    if "daily_return" in nav.columns and nav["daily_return"].notna().any():
        r = nav["daily_return"] / 100.0
        return r
    return nav["unit_nav"].pct_change()


def max_drawdown(nav: pd.DataFrame) -> dict:
    """最大回撤：幅度 + 峰谷日期 + 当前回撤（从最近峰值）。"""
    s = nav["unit_nav"].dropna().reset_index(drop=True)
    dates = nav["date"].dropna().reset_index(drop=True)
    if len(s) < 2:
        return {"max_drawdown_pct": 0.0, "peak_date": None, "trough_date": None, "current_drawdown_pct": 0.0}
    running_max = s.cummax()
    dd = (s - running_max) / running_max
    trough = int(dd.idxmin())
    peak = int(s.iloc[: trough + 1].idxmax())
    return {
        "max_drawdown_pct": round(float(dd.min()) * 100, 2),
        "peak_date": str(dates.iloc[peak].date()),
        "trough_date": str(dates.iloc[trough].date()),
        "current_drawdown_pct": round(float(dd.iloc[-1]) * 100, 2),
    }


def annualized_return(nav: pd.DataFrame, years: float | None = None) -> float | None:
    """年化收益率。years=None 用全部历史长度推算。"""
    s = nav["unit_nav"].dropna()
    n = len(s)
    if n < 2:
        return None
    total_return = s.iloc[-1] / s.iloc[0] - 1
    if years is None:
        years = n / TRADING_DAYS
    if years <= 0:
        return None
    return (1 + total_return) ** (1 / years) - 1


def annualized_volatility(nav: pd.DataFrame) -> float | None:
    """年化波动率（日收益标准差 × √252）。"""
    r = daily_returns(nav).dropna()
    if len(r) < 2:
        return None
    return float(r.std() * np.sqrt(TRADING_DAYS))


def sharpe(nav: pd.DataFrame, rf: float = RISK_FREE) -> float | None:
    """夏普比率 = (年化收益 - 无风险) / 年化波动。"""
    vol = annualized_volatility(nav)
    ann = annualized_return(nav)
    if not vol or not ann or vol == 0:
        return None
    return (ann - rf) / vol


def sortino(nav: pd.DataFrame, rf: float = RISK_FREE) -> float | None:
    """索提诺比率 = (年化收益 - 无风险) / 下行波动。"""
    r = daily_returns(nav).dropna()
    ann = annualized_return(nav)
    downside = r[r < 0].std() * np.sqrt(TRADING_DAYS)
    if downside == 0 or ann is None:
        return None
    return (ann - rf) / float(downside)


def calmar(nav: pd.DataFrame) -> float | None:
    """卡玛比率 = 年化收益 / |最大回撤|。"""
    mdd = max_drawdown(nav)["max_drawdown_pct"] / 100.0
    ann = annualized_return(nav)
    if mdd == 0 or ann is None:
        return None
    return ann / abs(mdd)


def period_returns(nav: pd.DataFrame) -> dict:
    """近 1月/3月/6月/1年/3年 区间收益率（%）。"""
    s = nav["unit_nav"].dropna().reset_index(drop=True)
    out = {}
    for label, days in [("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252), ("3y", 756)]:
        if len(s) > days:
            out[label] = round(float(s.iloc[-1] / s.iloc[-days - 1] - 1) * 100, 2)
        else:
            out[label] = None
    out["since_inception"] = round(float(s.iloc[-1] / s.iloc[0] - 1) * 100, 2) if len(s) > 1 else None
    return out


def compute_all(nav: pd.DataFrame) -> dict:
    """汇总所有风险收益指标 → dict（写 metrics.json）。"""
    ann = annualized_return(nav)
    vol = annualized_volatility(nav)
    return {
        "period_returns_pct": period_returns(nav),
        "annualized_return_pct": round(ann * 100, 2) if ann is not None else None,
        "annualized_volatility_pct": round(vol * 100, 2) if vol is not None else None,
        "sharpe": round(sharpe(nav), 3) if sharpe(nav) is not None else None,
        "sortino": round(sortino(nav), 3) if sortino(nav) is not None else None,
        "calmar": round(calmar(nav), 3) if calmar(nav) is not None else None,
        "drawdown": max_drawdown(nav),
        "latest_nav": round(float(nav["unit_nav"].dropna().iloc[-1]), 4),
        "latest_date": str(nav["date"].dropna().iloc[-1].date()),
        "data_points": int(nav["unit_nav"].notna().sum()),
    }


if __name__ == "__main__":
    import akshare as ak

    df = ak.fund_open_fund_info_em(symbol="161725", period="近期")
    df = df.rename(columns={"净值日期": "date", "单位净值": "unit_nav", "日增长率": "daily_return"})
    df["date"] = pd.to_datetime(df["date"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    import json
    print(json.dumps(compute_all(df), ensure_ascii=False, indent=2))
