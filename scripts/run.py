"""run.py — 基金右侧交易分析 · 两段式入口（v0.4 含板块联动 + 消息面 + 宽基）

用法：
  py scripts/run.py 161725              # 完整流程（stage1 → agent 介入点 → stage2）
  py scripts/run.py 161725 --quick      # 跳过 agent 介入，直出作战卡 + HTML 报告

数据流转：
  raw_data.json → metrics.json → signals.json → sector.json → rightside.json
                                                    ↓
                                    [agent_analysis.json]  ← agent 介入写入
                                                    ↓
                          reports/{code}_{date}/battle-card.md + report.html
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ["NO_PROXY"] = "*"  # bypass Windows 系统代理，避免 eastmoney 行情域名连接失败

import numpy as np
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "lib"))  # lib 内部统一用 `from xxx import`，__main__ 单跑也一致

from data_fetcher import (  # noqa: E402
    fetch_nav, fetch_holdings, fetch_industry_allocation, fetch_fund_name,
)
from risk_metrics import compute_all  # noqa: E402
from trend_signals import compute_signals  # noqa: E402
from right_side_engine import decide, render_battle_card  # noqa: E402
from sector_exposure import identify_sector, industry_snapshot  # noqa: E402
from sector_resonance import compute_resonance  # noqa: E402
from report_render import render_html  # noqa: E402


# ---------------------------- 工具 ----------------------------

def _json_default(o):
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not serializable: {type(o)}")


def cache_dir(code: str) -> Path:
    d = SKILL_DIR / ".cache" / code
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def progress(pct: int, msg: str) -> None:
    filled = pct // 5
    bar = "█" * filled + "░" * (20 - filled)
    print(f"[{bar}] {pct}% · {msg}")


# ---------------------------- 板块采集（降级友好） ----------------------------

def _collect_sector(code: str, signals: dict) -> dict:
    """板块识别 + 共振信号灯。任何环节失败都降级，不阻断主流程。"""
    cache = cache_dir(code)
    try:
        name, ftype = fetch_fund_name(code)
        holdings, hy = None, None
        for yr in ["2025", "2024"]:
            try:
                h = fetch_holdings(code, yr)
                if h is not None and len(h):
                    holdings, hy = h, yr
                    break
            except Exception:
                continue
        industry = None
        if hy:
            try:
                industry = fetch_industry_allocation(code, hy)
            except Exception:
                pass
        sector_id = identify_sector(name, holdings)
        sector = compute_resonance(signals, sector_id["index_symbols"], code)
        sector["sector_id"] = sector_id
        sector["fund_name"] = name
        sector["fund_type"] = ftype
        sector["holdings_year"] = hy
        sector["industry_snapshot"] = industry_snapshot(industry)
    except Exception as e:
        sector = {"available": False, "light": "⚪", "label": f"板块分析失败: {e}",
                  "advice": "", "fund_code": code}
    save_json(cache / "sector.json", sector)
    return sector


# ---------------------------- Stage 1 ----------------------------

def stage1(code: str) -> dict:
    cache = cache_dir(code)

    progress(8, f"采集 {code} 历史净值（天天基金）…")
    nav = fetch_nav(code, period="全部")
    if len(nav) < 60:
        raise ValueError(f"{code} 净值数据不足（仅 {len(nav)} 条），至少需要 60 个交易日")
    nav_records = nav.assign(date=nav["date"].dt.strftime("%Y-%m-%d")).to_dict("records")
    save_json(cache / "raw_data.json", {"fund_code": code, "rows": len(nav), "nav": nav_records})
    nav.to_csv(cache / "net_value.csv", index=False, encoding="utf-8-sig")

    progress(35, "计算风险收益指标（回撤/波动/夏普/卡玛）…")
    metrics = compute_all(nav)
    metrics["fund_code"] = code
    save_json(cache / "metrics.json", metrics)

    progress(52, "计算周线趋势信号（20/60 周 + 更高低点 + 突破）…")
    signals = compute_signals(nav)
    save_json(cache / "signals.json", signals)

    progress(70, "板块识别 + 共振信号灯…")
    sector = _collect_sector(code, signals)

    progress(85, "生成右侧骨架决策（建仓/加仓/止盈/止损）…")
    decision = decide(metrics, signals, sector)
    save_json(cache / "rightside.json", decision)

    progress(100, f"stage1 完成 · 趋势={signals['trend']['regime']} · "
                  f"板块={sector.get('label', '?')} · {decision['action']}")
    return {"nav": nav, "metrics": metrics, "signals": signals, "sector": sector, "decision": decision}


# ---------------------------- Stage 2 ----------------------------

def stage2(code: str, s1: dict) -> tuple[Path, Path]:
    cache = cache_dir(code)
    agent_path = cache / "agent_analysis.json"
    agent = json.loads(agent_path.read_text(encoding="utf-8")) if agent_path.exists() else None

    decision = s1["decision"]
    metrics = s1["metrics"]
    signals = s1["signals"]
    sector = s1.get("sector", {})

    if agent and agent.get("sector_news"):
        decision["sector_news"] = agent["sector_news"]

    card = render_battle_card(decision, metrics, signals, code)
    if agent and agent.get("commentary"):
        card += f"\n\n## 🧠 Agent 定性研判\n\n{agent['commentary']}\n"
    elif agent is None:
        card += "\n\n> ℹ️ 未检测到 agent_analysis.json（纯脚本模式）。\n"

    report_dir = SKILL_DIR / "reports" / f"{code}_{datetime.now():%Y%m%d}"
    report_dir.mkdir(parents=True, exist_ok=True)
    md_out = report_dir / "battle-card.md"
    md_out.write_text(card, encoding="utf-8")

    html = render_html(decision, metrics, signals, s1["nav"], code,
                       sector.get("fund_name", ""), sector)
    html_out = report_dir / "report.html"
    html_out.write_text(html, encoding="utf-8")
    return md_out, html_out


def _load_stage1_from_cache(code: str) -> dict:
    """从 .cache 读 stage1 产物（--stage2 用，深度模式避免重抓数据）。"""
    cache = cache_dir(code)
    nav = pd.read_csv(cache / "net_value.csv", parse_dates=["date"])
    nav = nav.sort_values("date").reset_index(drop=True)
    metrics = json.loads((cache / "metrics.json").read_text(encoding="utf-8"))
    signals = json.loads((cache / "signals.json").read_text(encoding="utf-8"))
    sector = json.loads((cache / "sector.json").read_text(encoding="utf-8"))
    decision = json.loads((cache / "rightside.json").read_text(encoding="utf-8"))
    return {"nav": nav, "metrics": metrics, "signals": signals, "sector": sector, "decision": decision}


def _open_html(path: Path) -> None:
    """跨平台自动打开 HTML 报告（Windows os.startfile / Mac open / Linux xdg-open）。失败只提示，不阻断。"""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        print(f"（自动打开失败：{e}。请手动打开：{path}）")


# ---------------------------- CLI ----------------------------

def main():
    parser = argparse.ArgumentParser(description="基金右侧交易分析（两段式 + 板块联动）")
    parser.add_argument("code", help="基金代码，如 161725")
    parser.add_argument("--quick", action="store_true", help="stage1+stage2 一把跑（默认快速模式，无 agent）")
    parser.add_argument("--stage1", action="store_true", help="只跑 stage1（深度模式第1步，停在 agent 介入点）")
    parser.add_argument("--stage2", action="store_true", help="只跑 stage2（深度模式第3步，读 .cache + agent_analysis）")
    parser.add_argument("--no-open", action="store_true", help="不自动打开 HTML 报告")
    args = parser.parse_args()

    if args.stage1:
        stage1(args.code)
        print(f"\n⏸️  stage1 完成。Agent 介入：读 .cache/{args.code}/rightside.json + sector.json，"
              f"WebSearch 搜板块消息面，写 agent_analysis.json，再跑：py run.py {args.code} --stage2")
        return

    if args.stage2:
        s1 = _load_stage1_from_cache(args.code)
        md_out, html_out = stage2(args.code, s1)
        print(f"\n✅ 作战卡：{md_out}\n✅ HTML 报告：{html_out}")
        if not args.no_open:
            _open_html(html_out)
        return

    s1 = stage1(args.code)
    if not args.quick:
        print(f"\n⏸️  stage1 完成。深度模式：写 agent_analysis.json 后跑 `py run.py {args.code} --stage2`。\n")
    md_out, html_out = stage2(args.code, s1)
    print(f"\n✅ 作战卡：{md_out}\n✅ HTML 报告：{html_out}")
    if not args.no_open:
        _open_html(html_out)


if __name__ == "__main__":
    main()
