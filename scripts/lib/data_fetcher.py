"""data_fetcher.py — akshare 基金数据采集封装

封装国内场外基金的数据接口，统一返回标准化的 DataFrame。
MVP 优先跑通净值（NAV）；持仓 / 行业配置 / 基金经理接口预置，供 Phase 2 板块联动用。

数据源：东方财富-天天基金（经 akshare）。场外基金净值是日级 T+1 数据。

⚠️ 硬约束：场外基金一天只有一个净值（收盘后公布），无实时价。
   右侧交易只能做日/周级中长线趋势跟踪，不能做日内。
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


# ---------------------------- 净值（MVP 核心） ----------------------------

def fetch_nav(symbol: str, period: str = "全部") -> pd.DataFrame:
    """获取基金历史净值。

    Args:
        symbol: 基金代码，如 "161725"（招商中证白酒联接）
        period: "近期" / "全部"。默认 "全部"（成立以来全部日净值）

    Returns:
        DataFrame，列 [date, unit_nav, accum_nav, daily_return]，按日期升序。
        date 为 datetime，其余为 float。
    """
    df = ak.fund_open_fund_info_em(symbol=symbol, period=period)

    # 容错：不同 akshare 版本列名可能有差异，按关键词匹配
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
