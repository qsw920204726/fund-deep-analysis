"""data_fetcher.py — akshare 基金数据采集封装

封装国内基金数据接口（场内 ETF + 场外基金），统一返回标准化的 DataFrame。
MVP 优先跑通净值/行情（NAV）；持仓 / 行业配置 / 基金经理接口预置，供 Phase 2 板块联动用。

数据源：东方财富-天天基金（经 akshare）。
- 场外基金：fund_open_fund_info_em，日级 T+1 净值
- 场内 ETF：fund_etf_hist_em，日K行情（前复权），含成交量

⚠️ 硬约束：场外基金一天只有一个净值（收盘后公布），无实时价；
   场内 ETF 有日内行情但本 skill 只做日/周级中长线趋势跟踪，不做日内。
"""
from __future__ import annotations

import os

# bypass Windows 系统代理（IE/注册表代理），避免 push2.eastmoney.com 等行情域名 SSL 握手失败
os.environ["NO_PROXY"] = "*"

import pandas as pd

try:
    import akshare as ak
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "akshare 未安装。请在 skill 目录执行：py -m pip install -r requirements.txt"
    ) from e


# 列名标准化映射（akshare 返回中文列名，统一成英文便于后续处理）
_NAV_COL_MAP = {
    "净值日期": "date",
    "单位净值": "unit_nav",
    "累计净值": "accum_nav",
    "日增长率": "daily_return",
}

# ETF 行情列名映射（fund_etf_hist_em 返回中文列名，收盘价统一映射成 unit_nav）
_ETF_COL_MAP = {
    "日期": "date", "开盘": "open", "收盘": "unit_nav",
    "最高": "high", "最低": "low", "成交量": "volume",
    "成交额": "amount", "涨跌幅": "daily_return",
}

_ETF_CODE_CACHE: set[str] | None = None


def is_etf(symbol: str) -> bool:
    """判断代码是否为场内 ETF（fund_etf_spot_em 代码集合，进程内缓存）。"""
    import time
    global _ETF_CODE_CACHE
    if _ETF_CODE_CACHE is None:
        for attempt in range(3):
            try:
                spot = ak.fund_etf_spot_em()
                code_col = next((c for c in spot.columns if "代码" in str(c)), None)
                _ETF_CODE_CACHE = set(spot[code_col].astype(str).str.strip()) if code_col else set()
                break
            except Exception:
                if attempt < 2:
                    time.sleep(3)
                else:
                    _ETF_CODE_CACHE = set()
    return symbol in _ETF_CODE_CACHE


# ---------------------------- 净值（MVP 核心） ----------------------------

def fetch_nav(symbol: str, period: str = "全部") -> pd.DataFrame:
    """获取基金历史净值/行情（自动识别场内 ETF / 场外基金）。

    Args:
        symbol: 基金代码。场内 ETF 如 "510300"（沪深300ETF）；场外如 "161725"（白酒联接）
        period: 场外 "近期"/"全部"；场内 ETF 忽略此参数（拉全部日K，前复权）

    Returns:
        DataFrame，列 [date, unit_nav, accum_nav, daily_return, volume?]，按日期升序。
        场内 ETF 额外含 volume（成交量），收盘价映射为 unit_nav 供下游统一消费。
    """
    if is_etf(symbol):
        return _fetch_etf_nav(symbol)
    return _fetch_of_nav(symbol, period)


def _fetch_of_nav(symbol: str, period: str) -> pd.DataFrame:
    """场外基金净值（fund_open_fund_info_em，日级 T+1）。"""
    df = ak.fund_open_fund_info_em(symbol=symbol, period=period)

    rename = {}
    for col in df.columns:
        lowered = str(col)
        if "日期" in lowered:
            rename[col] = "date"
        elif "单位净值" in lowered:
            rename[col] = "unit_nav"
        elif "累计净值" in lowered:
            rename[col] = "accum_nav"
        elif "增长" in lowered:
            rename[col] = "daily_return"
    df = df.rename(columns=rename)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    for col in ("unit_nav", "accum_nav", "daily_return"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _etf_sina_symbol(code: str) -> str:
    """6位代码 → 新浪源带前缀符号（沪市 sh / 深市 sz）。ETF 代码 5/6 开头为沪，1/0 开头为深。"""
    return ("sh" if code[0] in "56" else "sz") + code


def _fetch_etf_nav(symbol: str) -> pd.DataFrame:
    """场内 ETF 行情（fund_etf_hist_sina 新浪源，日K收盘价作为 unit_nav）。

    新浪源返回不复权原始价格（ETF 分红频率低，影响有限）。东方财富行情域名
    (push2his.eastmoney.com) 在部分网络环境被阻断，故用新浪源作为主数据源。
    """
    sina_sym = _etf_sina_symbol(symbol)
    import time
    df = None
    for attempt in range(3):
        try:
            df = ak.fund_etf_hist_sina(symbol=sina_sym)
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                raise RuntimeError(f"ETF 行情采集失败（重试3次）: {e}") from e

    # 新浪源字段: date, prevclose, open, high, low, close, volume, amount, postVol, postAmt
    df = df.rename(columns={"date": "date", "close": "unit_nav", "volume": "volume"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    # 涨跌幅：用收盘价 pct_change 计算（新浪源无涨跌幅字段）
    df["daily_return"] = df["unit_nav"].pct_change() * 100
    df["accum_nav"] = None  # ETF 无累计净值概念
    return df


# ---------- 持仓 / 行业 / 经理（Phase 2 板块联动用，先预置） ----------

def fetch_holdings(symbol: str, year: str) -> pd.DataFrame:
    """获取某年度前十大重仓股明细（按季度披露）。

    Args:
        symbol: 基金代码
        year: 年份字符串，如 "2024"
    """
    return ak.fund_portfolio_hold_em(symbol=symbol, date=year)


def fetch_industry_allocation(symbol: str, year: str) -> pd.DataFrame:
    """获取某年度行业配置（板块暴露的关键数据）。

    Returns 含：行业类别、占净值比例(%)、市值、季度 等。
    """
    return ak.fund_portfolio_industry_allocation_em(symbol=symbol, date=year)


def fetch_manager(symbol: str) -> pd.DataFrame:
    """获取基金经理信息（任职期间、任职回报）。Phase 2 细化。"""
    # fund_manager_em 全量返回，按 symbol 过滤；具体列名待 Phase 2 确认
    df = ak.fund_manager_em()
    sym_col = next((c for c in df.columns if "代码" in str(c)), None)
    if sym_col is not None:
        df = df[df[sym_col].astype(str).str.contains(symbol)]
    return df


_FUND_NAME_CACHE = None


def fetch_fund_name(symbol: str) -> tuple[str, str]:
    """查基金简称 + 类型（fund_name_em 全量字典，进程内缓存）。返回 (name, type)。"""
    global _FUND_NAME_CACHE
    if _FUND_NAME_CACHE is None:
        _FUND_NAME_CACHE = ak.fund_name_em()
    row = _FUND_NAME_CACHE[_FUND_NAME_CACHE["基金代码"].astype(str) == symbol]
    if not len(row):
        return ("", "")
    r = row.iloc[0]
    return (str(r.get("基金简称", "")), str(r.get("基金类型", "")))


if __name__ == "__main__":
    # 自检：抓 161725 最近净值
    nav = fetch_nav("161725", period="近期")
    print(f"抓到 {len(nav)} 条净值记录")
    print(nav.tail(5).to_string(index=False))
