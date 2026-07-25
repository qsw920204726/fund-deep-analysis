"""portfolio.py — 组合体检（多基金相关性 + 行业暴露重叠）

防"单只都对、组合集中爆雷"。输入多只基金，算净值收益率相关性矩阵 +
行业暴露重叠，提示隐性集中风险。

独立工具（不走 run.py 单基金流程）：py portfolio.py <代码1> <代码2> [代码3 ...]
"""
from __future__ import annotations

import os
from collections import Counter

os.environ["NO_PROXY"] = "*"

import pandas as pd

from data_fetcher import fetch_nav, fetch_fund_name, fetch_holdings
from sector_exposure import identify_sector


def portfolio_check(fund_codes: list[str]) -> dict:
    """多基金组合体检：相关性矩阵 + 行业暴露重叠 + 风险提示。"""
    names: dict[str, str] = {}
    sectors: dict[str, str | None] = {}
    ret_series: dict[str, pd.Series] = {}

    for code in fund_codes:
        nav = fetch_nav(code)
        nav = nav.dropna(subset=["unit_nav"]).reset_index(drop=True)
        name, _ = fetch_fund_name(code)
        names[code] = name
        r = nav["unit_nav"].pct_change().dropna()
        r.index = pd.to_datetime(nav["date"].iloc[1:])
        ret_series[code] = r

        holdings = None
        for yr in ["2025", "2024"]:
            try:
                h = fetch_holdings(code, yr)
                if h is not None and len(h):
                    holdings = h; break
            except Exception:
                pass
        sectors[code] = identify_sector(name, holdings).get("main_sector") or "未识别"

    # 相关性矩阵（按日期对齐，用重叠期）
    ret_df = pd.DataFrame(ret_series)
    corr = ret_df.corr()
    corr_dict = {
        c1: {c2: (round(float(corr.loc[c1, c2]), 2) if pd.notna(corr.loc[c1, c2]) else None)
             for c2 in fund_codes}
        for c1 in fund_codes
    }

    # 行业暴露重叠（多只同板块）
    sector_counts = Counter(sectors.values())
    overlap = {s: c for s, c in sector_counts.items() if c > 1 and s and s != "未识别"}

    # 高相关对（>0.7）
    high_corr = []
    for i in range(len(fund_codes)):
        for j in range(i + 1, len(fund_codes)):
            c = corr.loc[fund_codes[i], fund_codes[j]]
            if pd.notna(c) and c > 0.7:
                high_corr.append({"a": fund_codes[i], "b": fund_codes[j],
                                  "a_name": names[fund_codes[i]], "b_name": names[fund_codes[j]],
                                  "corr": round(float(c), 2)})

    # 警告
    warnings = []
    if overlap:
        warnings.append("⚠️ 行业集中：" + "、".join(f"{s}×{c} 只" for s, c in overlap.items())
                        + "（多只同板块，风险未真正分散）")
    if high_corr:
        warnings.append("⚠️ 高相关（>0.7）：" + "、".join(f"{h['a']}-{h['b']}={h['corr']}" for h in high_corr)
                        + "（同涨同跌，分散度低）")
    avg_off_diag = []
    for i in range(len(fund_codes)):
        for j in range(i + 1, len(fund_codes)):
            c = corr.loc[fund_codes[i], fund_codes[j]]
            if pd.notna(c):
                avg_off_diag.append(float(c))
    avg_corr = round(sum(avg_off_diag) / len(avg_off_diag), 2) if avg_off_diag else None
    if not warnings:
        warnings.append("✅ 组合分散度良好（无显著行业集中或高相关）")
    if avg_corr is not None and avg_corr > 0.6:
        warnings.append(f"⚠️ 组合平均相关系数 {avg_corr} 偏高，整体同向波动大")

    return {
        "funds": {c: {"name": names[c], "sector": sectors[c]} for c in fund_codes},
        "corr_matrix": corr_dict,
        "avg_corr": avg_corr,
        "sector_overlap": overlap,
        "high_corr_pairs": high_corr,
        "warnings": warnings,
    }


def render_portfolio_report(result: dict) -> str:
    funds = result["funds"]
    codes = list(funds.keys())
    fund_rows = "\n".join(f"| {c} | {f['name'][:18]} | {f['sector']} |" for c, f in funds.items())
    corr = result["corr_matrix"]
    header = "| | " + " | ".join(codes) + " |"
    sep = "|---|" + "---|" * len(codes)
    corr_rows = "\n".join(f"| **{c}** | " + " | ".join(str(corr[c][c2]) for c2 in codes) + " |" for c in codes)
    overlap = result["sector_overlap"]
    overlap_txt = "、".join(f"{s}×{c}只" for s, c in overlap.items()) if overlap else "无显著重叠（分散良好）"
    warns = "\n".join(f"- {w}" for w in result["warnings"])

    return f"""# 组合体检（{len(codes)} 只基金 · 平均相关 {result.get('avg_corr','—')}）

## 基金与主板块
| 代码 | 简称 | 主板块 |
|---|---|---|
{fund_rows}

**行业暴露重叠**：{overlap_txt}

## 净值收益率相关性矩阵
{header}
{sep}
{corr_rows}

> >0.7 高相关（同涨同跌）｜0.3-0.7 中相关｜<0.3 低相关（分散好）｜负相关最理想但基金少见

## 风险提示
{warns}

---
⚠️ **单只基金都对，不代表组合安全**。相关性高/行业集中 = 隐性风险叠加。
建议跨板块（消费+科技+金融+黄金）+ 低相关搭配，别凑一堆白酒/消费。
"""


if __name__ == "__main__":
    import sys

    codes = sys.argv[1:]
    if len(codes) < 2:
        print("用法: py portfolio.py <代码1> <代码2> [代码3 ...]  (至少 2 只)")
        sys.exit(1)
    print(render_portfolio_report(portfolio_check(codes)))
