"""run.py — 基金右侧交易分析 · 两段式入口（v0.5：持仓状态机 + 量能/板块门控 + 双日确认 + 基准回测）

用法：
  python scripts/run.py 161725              # 深度模式 stage1，等待 Codex 介入
  python scripts/run.py 161725 --quick      # 跳过 Codex 介入，直出作战卡 + HTML 报告

数据流转：
  raw_data.json → metrics.json → signals.json → sector.json → rightside.json
                                                    ↓
                                    [agent_analysis.json]  ← agent 介入写入
                                                    ↓
                          reports/{code}_{date}/battle-card.md + report.html

外部工具链（可选增强，v0.6）：
  --enrich-flow    用 a-stock-data 补齐板块/个股资金流 + 龙虎榜 + 北向 → sector.json.capital_flow
  --vibe-backtest  导出右侧信号 run_dir 并调用 Vibe-Trading MCP 独立回测 → rightside.json.vibe_backtest
  任一环节失败自动降级，不阻断主流程。
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
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "lib"))  # lib 内部统一用 `from xxx import`，__main__ 单跑也一致


def default_runtime_dir() -> Path:
    return Path.cwd().resolve() / "fund-deep-analysis-output"


RUNTIME_DIR = default_runtime_dir()


def configure_runtime_dir(path: str | Path) -> Path:
    global RUNTIME_DIR
    RUNTIME_DIR = Path(path).expanduser().resolve()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR


def report_dir(code: str, date_stamp: str) -> Path:
    return RUNTIME_DIR / "reports" / f"{code}_{date_stamp}"

from data_fetcher import (  # noqa: E402
    fetch_nav, fetch_holdings, fetch_industry_allocation, fetch_fund_name,
)
from risk_metrics import compute_all  # noqa: E402
from trend_signals import compute_signals  # noqa: E402
from right_side_engine import decide, render_battle_card  # noqa: E402
from sector_exposure import identify_sector, industry_snapshot  # noqa: E402
from sector_resonance import compute_resonance  # noqa: E402
from report_render import render_html  # noqa: E402
from backtest import backtest  # noqa: E402
from valuation import compute_valuation  # noqa: E402


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
    d = RUNTIME_DIR / ".cache" / code
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def progress(pct: int, msg: str) -> None:
    filled = pct // 5
    bar = "█" * filled + "░" * (20 - filled)
    print(f"[{bar}] {pct}% · {msg}")


# ---------------------------- 板块采集（降级友好） ----------------------------

def _collect_sector(code: str, signals: dict, enrich_flow: bool = False) -> dict:
    """板块识别 + 共振信号灯（可选资金面增强）。任何环节失败都降级，不阻断主流程。"""
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
        snap = industry_snapshot(industry)
        sector_id = identify_sector(name, holdings, industry_top3=(snap or {}).get("top3"))
        sector = compute_resonance(signals, sector_id["index_symbols"], code)
        sector["sector_id"] = sector_id
        sector["fund_name"] = name
        sector["fund_type"] = ftype
        sector["holdings_year"] = hy
        sector["industry_snapshot"] = snap
        if enrich_flow:
            try:
                from toolchain import enrich_capital_flow, global_stock_hint
                cf = enrich_capital_flow(code, sector_id, holdings, name)
                if not cf.get("available") and cf.get("error"):
                    print(f"  ⚠️ 资金面增强跳过：{cf['error']}")
                else:
                    sector["capital_flow"] = cf
                    print("  ✅ 资金面增强（a-stock-data）：板块/个股资金流 + 龙虎榜 + 北向 已并入")
                gh = global_stock_hint(holdings)
                if gh.get("available"):
                    sector["global_stock_hint"] = gh
                    print(f"  🌏 重仓含港股/美股（{len(gh['hits'])} 只），建议 agent 用 global-stock-data 穿透核验")
            except Exception as e2:
                print(f"  ⚠️ 资金面增强异常（降级）：{e2!r}")
    except Exception as e:
        sector = {"available": False, "light": "⚪", "label": f"板块分析失败: {e}",
                  "advice": "", "fund_code": code}
    save_json(cache / "sector.json", sector)
    return sector


# ---------------------------- Stage 1 ----------------------------

def stage1(code: str, state: dict | None = None, *,
           enrich_flow: bool = False, vibe_backtest: bool = False) -> dict:
    cache = cache_dir(code)

    progress(8, f"采集 {code} 历史净值（天天基金）…")
    nav = fetch_nav(code, period="全部")
    if len(nav) < 150:
        raise ValueError(
            f"{code} 净值数据不足（仅 {len(nav)} 条），至少需要 150 个交易日"
            f"（20 周均线需约 100 个交易日，60 周需约 300 个交易日；当前仅够 {len(nav) // 5} 周左右）")
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
    sector = _collect_sector(code, signals, enrich_flow=enrich_flow)

    progress(82, "生成右侧骨架决策（建仓/加仓/止盈/止损）…")
    decision = decide(metrics, signals, sector, state=state)

    progress(92, "回测右侧信号历史表现…")
    bt = backtest(nav)
    decision["backtest"] = bt

    progress(96, "估值锚（PE 历史分位）…")
    decision["valuation"] = compute_valuation(sector.get("sector_id", {}).get("main_sector"))

    if vibe_backtest:
        progress(98, "导出右侧信号 → Vibe-Trading MCP 独立回测…")
        try:
            from toolchain import export_vibe_run, run_vibe_backtest
            run_dir = export_vibe_run(code, sector.get("fund_name", ""), decision, nav, RUNTIME_DIR)
            decision["vibe_backtest"] = run_vibe_backtest(run_dir)
            if decision["vibe_backtest"].get("available"):
                print("  ✅ Vibe-Trading 回测完成，结果并入 rightside.json.vibe_backtest")
            else:
                print(f"  ⚠️ Vibe-Trading 回测不可用：{decision['vibe_backtest'].get('error')}")
        except Exception as e:
            decision["vibe_backtest"] = {"available": False, "error": f"{e!r}"}
            print(f"  ⚠️ Vibe-Trading 回测导出失败（降级）：{e!r}")

    save_json(cache / "rightside.json", decision)
    save_json(cache / "backtest.json", bt)

    progress(100, f"stage1 完成 · 趋势={signals['trend']['regime']} · "
                  f"板块={sector.get('label', '?')} · {decision['action']}")
    return {"nav": nav, "metrics": metrics, "signals": signals, "sector": sector, "decision": decision}


# ---------------------------- Stage 2 ----------------------------

def load_agent_analysis(path: Path, *, required: bool) -> dict | None:
    if not path.exists():
        if required:
            raise ValueError(f"缺少深度模式文件 agent_analysis.json: {path}")
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"agent_analysis.json 无法读取: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("agent_analysis.json 必须是 JSON 对象")
    commentary = payload.get("commentary")
    if not isinstance(commentary, str) or not commentary.strip():
        raise ValueError("agent_analysis.json.commentary 必须是非空字符串")

    news = payload.get("sector_news")
    required_news = {
        "sector", "as_of", "bullish", "bearish", "summary",
        "evidence_status", "sources",
    }
    if not isinstance(news, dict) or required_news - news.keys():
        raise ValueError("agent_analysis.json.sector_news 字段不完整")
    for field in ("sector", "as_of", "summary"):
        if not isinstance(news[field], str) or not news[field].strip():
            raise ValueError(f"sector_news.{field} 必须是非空字符串")
    try:
        datetime.strptime(news["as_of"], "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("sector_news.as_of 必须是 YYYY-MM-DD 日期") from exc

    if news["evidence_status"] not in {"verified", "unavailable"}:
        raise ValueError("evidence_status 必须是 verified 或 unavailable")
    if not all(isinstance(news[field], list) for field in ("bullish", "bearish", "sources")):
        raise ValueError("bullish、bearish 和 sources 必须是数组")

    if news["evidence_status"] == "unavailable":
        if news["sources"] or news["bullish"] or news["bearish"]:
            raise ValueError("unavailable 证据必须使用空的 bullish、bearish 和 sources")
        return payload

    if not news["sources"]:
        raise ValueError("verified 证据必须包含 sources")
    for source in news["sources"]:
        required_source = {"title", "date", "url", "stance", "summary"}
        if not isinstance(source, dict) or required_source - source.keys():
            raise ValueError("每个 source 必须包含 title/date/url/stance/summary")
        for field in required_source:
            if not isinstance(source[field], str) or not source[field].strip():
                raise ValueError(f"source.{field} 必须是非空字符串")
        try:
            datetime.strptime(source["date"], "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("source.date 必须是 YYYY-MM-DD 日期") from exc
        if not source["url"].startswith(("http://", "https://")):
            raise ValueError("source.url 必须是 HTTP(S) URL")
        if source["stance"] not in {"bullish", "bearish", "neutral"}:
            raise ValueError("source.stance 必须是 bullish、bearish 或 neutral")
    return payload


def stage2(code: str, s1: dict, *, require_agent: bool) -> tuple[Path, Path]:
    cache = cache_dir(code)
    agent_path = cache / "agent_analysis.json"
    agent = load_agent_analysis(agent_path, required=True) if require_agent else None

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

    output_dir = report_dir(code, f"{datetime.now():%Y%m%d}")
    output_dir.mkdir(parents=True, exist_ok=True)
    md_out = output_dir / "battle-card.md"
    md_out.write_text(card, encoding="utf-8")

    html = render_html(decision, metrics, signals, s1["nav"], code,
                       sector.get("fund_name", ""), sector)
    html_out = output_dir / "report.html"
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

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="基金右侧交易分析（两段式 + 板块联动）")
    parser.add_argument("code", help="基金代码，如 161725")
    parser.add_argument("--quick", action="store_true", help="stage1+stage2 快速模式，无外部消息面")
    parser.add_argument("--stage1", action="store_true", help="只运行深度模式 stage1")
    parser.add_argument("--stage2", action="store_true", help="只运行深度模式 stage2")
    parser.add_argument("--runtime-dir", default=None, help="缓存和报告的可写根目录")
    parser.add_argument("--state", choices=["empty", "holding"], default="empty",
                        help="视角：empty=空仓（默认） / holding=持仓（需 --entry 成本价，可选 --peak 入场后峰值）")
    parser.add_argument("--entry", type=float, default=None, help="持仓成本净值（--state holding 时必填）")
    parser.add_argument("--peak", type=float, default=None, help="入场后最高净值（--state holding 可选，默认=entry）")
    parser.add_argument("--open", dest="open_report", action="store_true", help="生成后打开 HTML 报告")
    parser.add_argument("--no-open", dest="open_report", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--enrich-flow", action="store_true",
                        help="用 a-stock-data 补齐板块/个股资金流 + 龙虎榜 + 北向（需已安装 a-stock-data skill）")
    parser.add_argument("--vibe-backtest", action="store_true",
                        help="导出右侧信号 run_dir 并调用 Vibe-Trading MCP 独立回测（需已安装 vibe-trading-ai）")
    parser.set_defaults(open_report=False)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    configure_runtime_dir(args.runtime_dir or default_runtime_dir())

    state = {"entry": args.entry, "peak": args.peak} if args.state == "holding" else None
    if args.state == "holding" and args.entry is None:
        parser.error("--state holding 必须提供 --entry 成本净值")

    if args.stage1:
        stage1(args.code, state=state, enrich_flow=args.enrich_flow,
               vibe_backtest=args.vibe_backtest)
        print(f"\n⏸️  stage1 完成。Agent 介入：读 .cache/{args.code}/rightside.json + sector.json，"
              f"检索板块消息面，写 agent_analysis.json，再运行 --stage2")
        return

    if args.stage2:
        s1 = _load_stage1_from_cache(args.code)
        md_out, html_out = stage2(args.code, s1, require_agent=True)
        print(f"\n✅ 作战卡：{md_out}\n✅ HTML 报告：{html_out}")
        if args.open_report:
            _open_html(html_out)
        return

    if not args.quick:
        stage1(args.code, state=state, enrich_flow=args.enrich_flow,
               vibe_backtest=args.vibe_backtest)
        print(f"\n⏸️  stage1 完成。深度模式：写 agent_analysis.json 后使用同一 Python 运行 `run.py {args.code} --stage2`。\n")
        return

    s1 = stage1(args.code, state=state, enrich_flow=args.enrich_flow,
                vibe_backtest=args.vibe_backtest)
    md_out, html_out = stage2(args.code, s1, require_agent=False)
    print(f"\n✅ 作战卡：{md_out}\n✅ HTML 报告：{html_out}")
    if args.open_report:
        _open_html(html_out)


if __name__ == "__main__":
    main()
