"""backtest.py — 右侧信号历史回测

把 skill 的右侧信号体系在历史周线上回测，验证这套信号历史上赚不赚。
回测的就是 skill 实际会给的信号（站上 20 周线 + 多头排列 + 均线拐头 + 更高低点 买入；
移动止盈 10% / 止损破前低 / 跌破均线 卖出），保证一致性。

⚠️ 回测假设：信号触发按周收盘价成交（无滑点/手续费），满仓单只复投。
   回测结果仅供参考，不代表未来。样本少的基金（<5 笔交易）统计意义弱。
"""
from __future__ import annotations

import pandas as pd

from trend_signals import to_weekly, _ma, _swing_lows, FAST_WEEKS, SLOW_WEEKS

TRAILING_STOP = 0.10


def _compound(rets: list[float]) -> float:
    prod = 1.0
    for r in rets:
        prod *= (1 + r)
    return prod - 1


def backtest(nav: pd.DataFrame, fast: int = FAST_WEEKS, slow: int = SLOW_WEEKS,
             trailing: float = TRAILING_STOP) -> dict:
    """回测右侧信号，返回胜率/收益统计 + 交易明细。

    Args:
        nav: 日净值 DataFrame（含 date, unit_nav）
    """
    weekly = to_weekly(nav)
    price = weekly["unit_nav"].reset_index(drop=True)
    ma_f = _ma(price, fast).reset_index(drop=True)
    ma_s = _ma(price, slow).reset_index(drop=True)

    trades: list[dict] = []
    position: dict | None = None

    i = slow
    while i < len(price) - 1:
        p = float(price.iloc[i])

        if position is None:
            # 买点：站上 ma_f + 多头排列 + ma_f 拐头向上 + 近 30 周更高低点
            recent = price.iloc[max(0, i - 30): i + 1].reset_index(drop=True)
            lows = _swing_lows(recent, k=3)
            higher_lows = len(lows) >= 2 and recent.iloc[lows[-1]] > recent.iloc[lows[-2]]
            buy = (
                pd.notna(ma_f.iloc[i]) and pd.notna(ma_s.iloc[i])
                and p > ma_f.iloc[i] and ma_f.iloc[i] > ma_s.iloc[i]
                and ma_f.iloc[i] > ma_f.iloc[i - 1]
                and higher_lows
            )
            if buy:
                stop = float(recent.iloc[lows[-1]]) if lows else p * 0.95
                position = {"entry": p, "peak": p, "stop": stop}
        else:
            if p > position["peak"]:
                position["peak"] = p
            trailing_stop = position["peak"] * (1 - trailing)
            # 卖出：触止损 / 触移动止盈 / 连续跌破 ma_f
            broke_ma = (pd.notna(ma_f.iloc[i]) and p < ma_f.iloc[i]
                        and p < float(price.iloc[i - 1]) and p < position["entry"])
            if p <= position["stop"]:
                reason = "止损"
                sell = True
            elif p <= trailing_stop and position["peak"] > position["entry"]:
                reason = "移动止盈"
                sell = True
            elif broke_ma:
                reason = "跌破均线"
                sell = True
            else:
                reason = ""
                sell = False
            if sell:
                trades.append({"entry": position["entry"], "exit": p,
                               "ret": p / position["entry"] - 1, "reason": reason})
                position = None
        i += 1

    # 期末平仓未结持仓
    if position is not None:
        p = float(price.iloc[-1])
        trades.append({"entry": position["entry"], "exit": p,
                       "ret": p / position["entry"] - 1, "reason": "期末平仓"})

    if not trades:
        return {"n_trades": 0, "win_rate": None, "avg_return_pct": None,
                "total_return_pct": None, "max_gain_pct": None, "max_loss_pct": None,
                "trades": []}

    rets = [t["ret"] for t in trades]
    wins = sum(1 for r in rets if r > 0)
    return {
        "n_trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 1),
        "avg_return_pct": round(sum(rets) / len(rets) * 100, 2),
        "total_return_pct": round(_compound(rets) * 100, 2),
        "max_gain_pct": round(max(rets) * 100, 2),
        "max_loss_pct": round(min(rets) * 100, 2),
        "trades": [{"ret_pct": round(t["ret"] * 100, 1), "reason": t["reason"]} for t in trades],
    }


if __name__ == "__main__":
    import akshare as ak
    import json

    df = ak.fund_open_fund_info_em(symbol="161725", period="近期")
    df = df.rename(columns={"净值日期": "date", "单位净值": "unit_nav", "日增长率": "daily_return"})
    df["date"] = pd.to_datetime(df["date"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    print(json.dumps(backtest(df), ensure_ascii=False, indent=2))
