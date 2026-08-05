"""backtest.py — 右侧信号历史回测 v0.5（与作战卡规则对齐）

回测的就是 skill 实际会给的信号与退出：
  - 买入：周线多头排列（价>MA20>MA60 且 MA20 向上）+ 更高低点结构
           （无 swing low 时用"连续 2 周站上 MA20"兜底，避免强趋势降仓）
  - 加仓：趋势延续创新高时金字塔 40→35→25（最多补到 100%）
  - 退出：
      ① 跌破 MA20 周线减 40%（TP2，与卡面一致）
      ② 跌破 MA60 周线清仓（TP3）
      ③ 双轨止损位（已确认 swing low 与最近 4 周低点取低者）跌破清仓
      ④ 自入场后峰值回撤 12% 移动止盈清仓

v0.5 改进：
  - 与卡面三档退出/止损/移动止盈规则统一（旧版是另一套简化规则）
  - 含买卖手续费（0.05%/边，可配）
  - 增加策略 vs 买入持有 的累计收益与最大回撤对比
  - 按周收盘价成交（无滑点），统计按"建仓→清仓"完整回合
"""
from __future__ import annotations

import pandas as pd

from trend_signals import to_weekly, _ma, _swing_lows, FAST_WEEKS, SLOW_WEEKS

TRAILING_STOP = 0.12
BUY_FEE = 0.0005    # 单边手续费（ETF 约 0.01%~0.03%，场外约 0.15%，取折中）
SELL_FEE = 0.0005
BASE_FRAC = 0.40    # 底仓
ADD1_FRAC = 0.35    # 第一次加仓（补到 75%）
ADD2_FRAC = 0.25    # 第二次加仓（补到 100%）
ADD2_TRIGGER = 1.10  # 第二次加仓需创新高 10%
MAX_CHASE_PCT = 0.05  # 追高上限：买入时价格最多高于 MA20 5%（与卡面"溢价过高勿追，等回踩"对齐）


def _swing_low_up_to(price: pd.Series, end_idx: int, k: int = 3, lookback: int = 26) -> float | None:
    """截至 end_idx（不含）的已确认 swing low（近 lookback 根周线）。"""
    start = max(0, end_idx - lookback)
    seg = price.iloc[start:end_idx].reset_index(drop=True)
    if len(seg) < k * 2 + 1:
        return None
    lows = _swing_lows(seg, k=k)
    return float(seg.iloc[lows[-1]]) if lows else None


def _stop_low_up_to(price: pd.Series, end_idx: int) -> float | None:
    """双轨止损：已确认 swing low 与最近 4 根（不含当根）最低收盘取低者。"""
    confirmed = _swing_low_up_to(price, end_idx)
    pending = float(price.iloc[max(0, end_idx - 4):end_idx].min()) if end_idx > 0 else None
    vals = [v for v in (confirmed, pending) if v is not None]
    return min(vals) if vals else None


def _higher_lows_up_to(price: pd.Series, end_idx: int, lookback: int = 30) -> bool:
    """截至 end_idx（含）的更高低点结构。"""
    start = max(0, end_idx - lookback + 1)
    seg = price.iloc[start:end_idx + 1].reset_index(drop=True)
    if len(seg) < 10:
        return False
    lows = _swing_lows(seg, k=3)
    if len(lows) < 2:
        return False
    return seg.iloc[lows[-1]] > seg.iloc[lows[-2]]


def backtest(nav: pd.DataFrame, fast: int = FAST_WEEKS, slow: int = SLOW_WEEKS,
             trailing: float = TRAILING_STOP) -> dict:
    """回测右侧信号，返回胜率/收益统计 + 基准对比 + 交易明细。"""
    weekly = to_weekly(nav)
    price = weekly["unit_nav"].reset_index(drop=True)
    ma_f = _ma(price, fast).reset_index(drop=True)
    ma_s = _ma(price, slow).reset_index(drop=True)

    cash = 1.0
    qty = 0.0
    entry_price: float | None = None
    entry_bar = 0
    peak = 0.0
    adds = 0
    trimmed = False  # 本轮是否已执行"跌破MA20减40%"
    round_entry_cost = 0.0
    round_shares_bought = 0.0
    round_exit_value = 0.0
    round_shares_sold = 0.0
    round_reason = ""
    trades: list[dict] = []
    equity_curve: list[float] = []

    i = slow
    while i < len(price):
        p = float(price.iloc[i])
        prev_p = float(price.iloc[i - 1]) if i > 0 else p
        has_f = pd.notna(ma_f.iloc[i])
        has_s = pd.notna(ma_s.iloc[i])

        # ---- 更新权益曲线 ----
        equity_curve.append(cash + qty * p)

        # ---- 已持仓：更新峰值与退出 ----
        if qty > 1e-12:
            peak = max(peak, p)
            stop = _stop_low_up_to(price, i)
            trailing_stop = peak * (1 - trailing)
            broke_f = has_f and p < ma_f.iloc[i] and p < prev_p
            broke_s = has_s and p < ma_s.iloc[i]
            reason = ""
            do_clear = False
            if stop is not None and p <= stop:
                reason, do_clear = "止损", True
            elif p <= trailing_stop and peak > entry_price:
                reason, do_clear = "移动止盈", True
            elif broke_s:
                reason, do_clear = "跌破MA60清仓", True
            elif broke_f and not trimmed and qty > 1e-9:
                # 跌破 MA20：减 40% 仓位（TP2，与卡面一致，每轮交易只触发一次）
                sell_qty = qty * 0.4
                proceeds = sell_qty * p * (1 - SELL_FEE)
                cash += proceeds
                qty -= sell_qty
                round_exit_value += proceeds
                round_shares_sold += sell_qty
                trimmed = True
                if not round_reason:
                    round_reason = "跌破MA20减仓"
            if do_clear:
                proceeds = qty * p * (1 - SELL_FEE)
                cash += proceeds
                round_exit_value += proceeds
                round_shares_sold += qty
                qty = 0.0
                if entry_price:
                    avg_entry = round_entry_cost / round_shares_bought if round_shares_bought else entry_price
                    avg_exit = round_exit_value / round_shares_sold if round_shares_sold else p
                    ret = avg_exit / avg_entry - 1
                    trades.append({
                        "entry": round(avg_entry, 4), "exit": round(avg_exit, 4),
                        "ret": ret, "ret_pct": round(ret * 100, 1),
                        "reason": reason or round_reason or "期末平仓",
                        "hold_weeks": i - entry_bar,
                    })
                entry_price = None
                adds = 0
                trimmed = False
                round_entry_cost = 0.0
                round_shares_bought = 0.0
                round_exit_value = 0.0
                round_shares_sold = 0.0
                round_reason = ""
            # 金字塔加仓（趋势延续创新高）
            elif has_f and p > ma_f.iloc[i] and adds < 2:
                if adds == 0 and p >= peak:
                    buy_frac = ADD1_FRAC
                elif adds == 1 and p >= peak * ADD2_TRIGGER:
                    buy_frac = ADD2_FRAC
                else:
                    buy_frac = 0.0
                if buy_frac > 0 and qty + buy_frac <= 1.0 + 1e-9:
                    cost = equity_curve[-1] * buy_frac
                    qty += cost * (1 - BUY_FEE) / p
                    cash -= cost
                    round_entry_cost += cost
                    round_shares_bought += cost * (1 - BUY_FEE) / p
                    adds += 1
        # ---- 空仓：右侧买入 ----
        elif has_f and has_s and p > ma_f.iloc[i] and ma_f.iloc[i] > ma_s.iloc[i] \
                and ma_f.iloc[i] > ma_f.iloc[i - 1] \
                and p <= ma_f.iloc[i] * (1 + MAX_CHASE_PCT) \
                and (_higher_lows_up_to(price, i) or
                     (i >= 2 and float(price.iloc[i - 1]) > ma_f.iloc[i - 1])):
            cost = equity_curve[-1] * BASE_FRAC
            qty += cost * (1 - BUY_FEE) / p
            cash -= cost
            entry_price = p
            entry_bar = i
            peak = p
            adds = 0
            trimmed = False
            round_entry_cost = cost
            round_shares_bought = cost * (1 - BUY_FEE) / p
            round_exit_value = 0.0
            round_shares_sold = 0.0
            round_reason = ""
        i += 1

    # 期末平仓未结持仓
    if qty > 1e-12 and entry_price:
        p = float(price.iloc[-1])
        proceeds = qty * p * (1 - SELL_FEE)
        cash += proceeds
        round_exit_value += proceeds
        round_shares_sold += qty
        qty = 0.0
        avg_entry = round_entry_cost / round_shares_bought if round_shares_bought else entry_price
        avg_exit = round_exit_value / round_shares_sold if round_shares_sold else p
        trades.append({
            "entry": round(avg_entry, 4), "exit": round(avg_exit, 4),
            "ret": avg_exit / avg_entry - 1, "ret_pct": round((avg_exit / avg_entry - 1) * 100, 1),
            "reason": "期末平仓", "hold_weeks": len(price) - 1 - entry_bar,
        })

    if not trades:
        return {"n_trades": 0, "win_rate": None, "avg_return_pct": None,
                "total_return_pct": None, "max_gain_pct": None, "max_loss_pct": None,
                "benchmark_return_pct": None, "strategy_max_drawdown_pct": None,
                "benchmark_max_drawdown_pct": None, "avg_hold_weeks": None,
                "trades": []}

    rets = [t["ret"] for t in trades]
    wins = sum(1 for r in rets if r > 0)

    def _max_dd(series: list[float]) -> float:
        peak_v = -1e18
        mdd = 0.0
        for v in series:
            peak_v = max(peak_v, v)
            if peak_v > 0:
                mdd = min(mdd, v / peak_v - 1)
        return round(mdd * 100, 2)

    bench_price = price.iloc[slow:].reset_index(drop=True)
    bench_ret = round((float(bench_price.iloc[-1]) / float(bench_price.iloc[0]) - 1) * 100, 2)
    strat_ret = round((cash - 1.0) * 100, 2)
    return {
        "n_trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 1),
        "avg_return_pct": round(sum(rets) / len(rets) * 100, 2),
        "total_return_pct": strat_ret,
        "max_gain_pct": round(max(rets) * 100, 2),
        "max_loss_pct": round(min(rets) * 100, 2),
        "benchmark_return_pct": bench_ret,
        "strategy_max_drawdown_pct": _max_dd(equity_curve),
        "benchmark_max_drawdown_pct": _max_dd([float(v) for v in bench_price.tolist()]),
        "avg_hold_weeks": round(sum(t.get("hold_weeks", 0) for t in trades) / len(trades), 1),
        "trades": [{"ret_pct": t["ret_pct"], "reason": t["reason"],
                    "hold_weeks": t.get("hold_weeks")} for t in trades],
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
    print(json.dumps(backtest(df), ensure_ascii=False, indent=2))
