"""sector_exposure.py — 基金主板块识别 + 板块暴露

从基金名称 + 重仓股名称 + 证监会行业配置识别主板块，映射到可拉取的板块指数。
不依赖 push2.eastmoney.com 的个股行业接口（该域名在本环境受限），
改用名称/重仓股/行业配置关键词匹配 —— 对指数基金和行业集中型基金准确率高。

v0.5 修复：
  1. 新增 软件/传媒/通信/电子 板块（指数代码已用 akshare 实测：
     软件→sz399363 国证算力（软件/算力代理）、传媒→sz399397 国证文化、
     通信→sz399389 国证通信、电子→sz399811 CSSW电子）
  2. 新增阶段④：证监会行业配置兜底（前三大行业占比>=40% 时按行业名映射板块），
     解决"名称/重仓无关键词但行业高度集中"的基金（如软件ETF嘉实 86% 软件服务）

板块指数走新浪源 stock_zh_index_daily（见 sector_resonance.py）。
"""
from __future__ import annotations

import pandas as pd

# 板块 → 新浪源指数 symbol（sz/sh + 代码）。已验证或常见代码；拿不到时运行时降级。
# 中证/国证行业指数，覆盖主流板块。
SECTOR_INDEX_MAP: dict[str, list[str]] = {
    "白酒": ["sz399997"],            # 中证白酒 ✅已验证
    "银行": ["sz399986"],            # 中证银行
    "券商": ["sz399975"],            # 中证全指证券公司
    "新能源汽车": ["sz399976"],       # 中证新能源汽车
    "医药": ["sh000933", "sz399386"],  # 中证医药卫生 / 国证医药
    "食品饮料": ["sz399938"],         # 国证食品饮料
    "主要消费": ["sh000932"],         # 中证主要消费
    "军工": ["sz399967", "sz399959"],  # 中证军工 / 中证国防
    "半导体": ["sz931865", "sz980017"],  # 中证半导体 / 国证芯片
    "光伏": ["sz931151"],            # 中证光伏
    "煤炭": ["sz399998"],            # 中证煤炭
    "有色金属": ["sh000819"],         # 有色金属
    "房地产": ["sz399393"],          # 国证房地产
    "电力": ["sz931559"],            # 中证电力
    "软件": ["sz399363"],            # 国证算力（软件/算力代理）✅2026-08 实测新鲜
    "传媒": ["sz399397"],            # 国证文化（传媒代理）✅实测
    "通信": ["sz399389"],            # 国证通信 ✅实测
    "电子": ["sz399811"],            # CSSW电子 ✅实测
}

# 宽基标识 → (中文名, 新浪源指数 symbol)。匹配时按 key 长度降序，避免"中证500"误匹配"中证A500"。
BROAD_BASE_INDEX: dict[str, tuple[str, str]] = {
    "沪深300": ("沪深300", "sh000300"),
    "中证A500": ("中证A500", "sh932000"),
    "中证1000": ("中证1000", "sh000852"),
    "中证800": ("中证800", "sh000906"),
    "中证500": ("中证500", "sh000905"),
    "创业板50": ("创业板50", "sz399673"),
    "创业板": ("创业板指", "sz399006"),
    "科创50": ("科创50", "sh000688"),
    "上证180": ("上证180", "sh000010"),
    "上证50": ("上证50", "sh000016"),
    "深证100": ("深证100", "sz399004"),
    "深证成指": ("深证成指", "sz399001"),
    "国证2000": ("国证2000", "sz399303"),
    "中证红利": ("中证红利", "sh000922"),
}

# 关键词 → 板块（顺序敏感：先具体后宽泛）
KEYWORD_TO_SECTOR: list[tuple[str, list[str]]] = [
    ("白酒", ["白酒", "酒"]),
    ("半导体", ["半导体", "芯片"]),
    ("光伏", ["光伏"]),
    ("新能源汽车", ["新能源汽车", "新能源车", "锂电池", "锂电", "新能源"]),
    ("医药", ["医药", "医疗", "生物", "创新药", "健康"]),
    ("银行", ["银行"]),
    ("券商", ["券商", "证券"]),
    ("军工", ["军工", "国防", "航天", "航空", "兵器"]),
    ("煤炭", ["煤炭"]),
    ("有色金属", ["有色", "黄金", "铜", "铝"]),
    ("房地产", ["地产", "房地产", "置业"]),
    ("电力", ["电力"]),
    ("食品饮料", ["食品", "饮料"]),
    ("主要消费", ["消费"]),
    ("软件", ["软件", "计算机", "信息技术", "信创", "云计算", "大数据", "算力", "互联网服务"]),
    ("传媒", ["传媒", "游戏", "影视", "动漫", "出版"]),
    ("通信", ["通信", "5G", "运营商", "光模块"]),
    ("电子", ["电子", "消费电子", "面板", "PCB"]),
]

# 证监会行业配置（大类/门类）→ 板块兜底
INDUSTRY_TO_SECTOR: list[tuple[str, str]] = [
    ("软件和信息技术服务业", "软件"),
    ("互联网和相关服务", "软件"),
    ("信息技术", "软件"),
    ("计算机", "软件"),
    ("文化、体育和娱乐业", "传媒"),
    ("电信、广播电视和卫星传输服务", "通信"),
    ("通信", "通信"),
    ("计算机、通信和其他电子设备制造业", "电子"),
    ("电子", "电子"),
    ("医药", "医药"),
    ("食品", "食品饮料"),
    ("饮料", "食品饮料"),
    ("酒", "白酒"),
    ("银行", "银行"),
    ("资本市场服务", "券商"),
    ("证券", "券商"),
    ("汽车", "新能源汽车"),
    ("电力", "电力"),
    ("煤炭", "煤炭"),
    ("有色金属", "有色金属"),
    ("房地产", "房地产"),
    ("国防", "军工"),
    ("铁路、船舶、航空航天", "军工"),
    ("电气机械", "光伏"),
    ("光伏", "光伏"),
]


def _match_keywords(text: str, sector_keywords: list[tuple[str, list[str]]]) -> tuple[str | None, str | None]:
    """按关键词顺序匹配，返回 (板块, 命中词)。"""
    for sector, keywords in sector_keywords:
        for kw in keywords:
            if kw in text:
                return sector, kw
    return None, None


def identify_sector(fund_name: str, holdings: pd.DataFrame | None,
                    industry_top3: list | None = None) -> dict:
    """识别主板块（五阶段）。

    ① 名称含宽基标识（沪深300/中证500/创业板等）→ 宽基类别 + 跟踪指数
    ② 名称含行业板块词（白酒/医药/银行…）→ 该板块
    ③ 前十大重仓 ≥4 只同一板块词 → 该板块（避免少数重仓误判）
    ④ 证监会行业配置 Top1 占比 >=40% → 按行业名映射板块（v0.5 新增）
    其余 → 未识别（均衡/主动配置型）
    """
    name = (fund_name or "").replace("　", " ")
    top_names = ""
    if holdings is not None and len(holdings) and "股票名称" in holdings.columns:
        top_names = " ".join(holdings["股票名称"].astype(str).head(10).tolist())

    # ① 宽基识别（跟踪大盘指数，有对应指数可做共振）
    for key in sorted(BROAD_BASE_INDEX.keys(), key=len, reverse=True):
        if key in name:
            cn, sym = BROAD_BASE_INDEX[key]
            return {"main_sector": f"宽基-{cn}", "matched_keyword": key,
                    "index_symbols": [sym],
                    "identification": f"宽基指数基金，跟踪{cn}（{sym}）",
                    "top_holdings": top_names[:60]}
    # ② 名称板块词
    sector, kw = _match_keywords(name, KEYWORD_TO_SECTOR)
    if sector:
        return {"main_sector": sector, "matched_keyword": kw,
                "index_symbols": SECTOR_INDEX_MAP.get(sector, []),
                "identification": f"基金名称含「{kw}」",
                "top_holdings": top_names[:60]}
    # ③ 重仓股集中度（≥4 只同一板块才算，避免少数重仓误判）
    if top_names:
        top = holdings["股票名称"].astype(str).head(10).tolist()
        # 重仓场景需要计数（>=4 只同板块才算）
        counts = {}
        for sec, keywords in KEYWORD_TO_SECTOR:
            c = sum(1 for n in top if any(k in n for k in keywords))
            if c:
                counts[sec] = counts.get(sec, 0) + c
        best = max(counts.items(), key=lambda kv: kv[1]) if counts else (None, 0)
        if best[0] and best[1] >= 4:
            return {"main_sector": best[0], "matched_keyword": f"{best[1]}只重仓",
                    "index_symbols": SECTOR_INDEX_MAP.get(best[0], []),
                    "identification": f"前十大重仓 {best[1]} 只属「{best[0]}」",
                    "top_holdings": top_names[:60]}
    # ④ 行业配置兜底（v0.5）：Top1 行业占比 >=40% 且能映射
    if industry_top3:
        for ind_name, weight in industry_top3[:3]:
            try:
                weight = float(weight)
            except Exception:
                continue
            if weight >= 40.0:
                sector, kw = _match_keywords(str(ind_name), INDUSTRY_TO_SECTOR)
                if sector:
                    return {"main_sector": sector, "matched_keyword": kw,
                            "index_symbols": SECTOR_INDEX_MAP.get(sector, []),
                            "identification": f"证监会行业配置「{ind_name}」占 {weight:.1f}%（≥40%）",
                            "top_holdings": top_names[:60]}
    return {"main_sector": None, "matched_keyword": None, "index_symbols": [],
            "identification": "未识别（重仓分散，主动配置型/均衡）",
            "top_holdings": top_names[:60]}


def industry_snapshot(industry_alloc: pd.DataFrame | None) -> dict | None:
    """从行业配置接口（证监会大类）取最新季度的 Top3 行业。仅作辅助参考。"""
    if industry_alloc is None or not len(industry_alloc):
        return None
    if "截止时间" in industry_alloc.columns:
        latest = industry_alloc["截止时间"].max()
        alloc = industry_alloc[industry_alloc["截止时间"] == latest]
    else:
        alloc = industry_alloc
    if "行业类别" in alloc.columns and "占净值比例" in alloc.columns:
        top = alloc.sort_values("占净值比例", ascending=False).head(3)
        return {
            "as_of": str(latest) if "截止时间" in industry_alloc.columns else None,
            "top3": [(r["行业类别"], float(r["占净值比例"])) for _, r in top.iterrows()],
        }
    return None


if __name__ == "__main__":
    import akshare as ak

    h = ak.fund_portfolio_hold_em(symbol="161725", date="2024")
    print("161725 板块识别：", identify_sector("招商中证白酒", h))
