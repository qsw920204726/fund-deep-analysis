"""valuation.py — 估值锚（板块/宽基 PE 历史分位）

用乐咕乐股 stock_index_pe_lg 拿指数 PE 历史，算当前 PE 的历史分位，
判断便宜/合理/贵，防止技术面在估值高位接盘。

⚠️ 数据源限制：lg 仅覆盖宽基（沪深300/上证50/中证500/中证1000/深证100）。
   行业指数（白酒/医药/银行…）lg 不支持，估值锚降级（建议人工查理杏仁/天天基金）。
"""
from __future__ import annotations

import os

os.environ["NO_PROXY"] = "*"

import pandas as pd

# main_sector → 乐咕乐股指数名（仅宽基；行业 lg 不覆盖）
LG_INDEX_MAP = {
    "宽基-沪深300": "沪深300",
    "宽基-上证50": "上证50",
    "宽基-中证500": "中证500",
    "宽基-中证1000": "中证1000",
    "宽基-深证100": "深证100",
}


def compute_valuation(main_sector: str | None, lookback_years: int = 5) -> dict:
    """算板块/宽基当前 PE 的近 N 年历史分位。

    Args:
        main_sector: sector_exposure 返回的主板块（如 "宽基-沪深300" / "白酒"）
    """
    if not main_sector:
        return {"available": False, "reason": "板块未识别，无估值锚"}
    lg_name = LG_INDEX_MAP.get(main_sector)
    if not lg_name:
        return {"available": False,
                "reason": f"{main_sector} 估值数据源未覆盖（lg 仅支持宽基），建议人工查理杏仁/天天基金"}

    try:
        import akshare as ak

        df = ak.stock_index_pe_lg(symbol=lg_name)
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values("日期").reset_index(drop=True)
        cutoff = df["日期"].max() - pd.Timedelta(days=365 * lookback_years)
        recent = df[df["日期"] >= cutoff]
        pe_col = "滚动市盈率" if "滚动市盈率" in df.columns else [c for c in df.columns if "滚动" in c][0]
        pe = pd.to_numeric(recent[pe_col], errors="coerce").dropna()
        if len(pe) < 50:
            return {"available": False, "reason": "PE 历史样本不足"}

        current = float(pe.iloc[-1])
        pct = round(float((pe < current).sum() / len(pe) * 100), 1)
        if pct < 20:
            verdict = "极便宜（低估区间）"
        elif pct < 40:
            verdict = "便宜偏低"
        elif pct < 60:
            verdict = "合理中位"
        elif pct < 80:
            verdict = "偏贵"
        else:
            verdict = "极贵（高估区间）"

        return {
            "available": True,
            "index_name": lg_name,
            "current_pe": round(current, 2),
            "pe_percentile": pct,
            "pe_min": round(float(pe.min()), 2),
            "pe_max": round(float(pe.max()), 2),
            "verdict": verdict,
            "lookback_years": lookback_years,
        }
    except Exception as e:
        return {"available": False, "reason": f"估值数据获取失败: {str(e)[:60]}"}


if __name__ == "__main__":
    import json

    print("=== 宽基-沪深300 ===")
    print(json.dumps(compute_valuation("宽基-沪深300"), ensure_ascii=False, indent=2))
    print("\n=== 白酒（行业，应降级）===")
    print(json.dumps(compute_valuation("白酒"), ensure_ascii=False, indent=2))
