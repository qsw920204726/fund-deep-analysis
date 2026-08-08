"""toolchain.py — 外部工具链桥接（v0.6，可选增强，任何失败都降级不阻断主流程）

适配的三个外部工具（由用户在 Codex 环境安装）：
  1. a-stock-data      → A 股板块/个股资金流 + 龙虎榜 + 北向资金（从已安装 SKILL.md 提取函数）
  2. global-stock-data → 港股/美股持仓穿透提示（重仓含港美股时提示 agent 调用该 skill 核验）
  3. Vibe-Trading MCP  → 右侧信号独立回测验证（导出 run_dir + 调用 vibe-trading-mcp stdio）

设计原则：
  - 所有能力均为"尽力而为"：找不到 skill / 提取失败 / 网络失败 → 返回 available=False + error，
    主流程照常出报告。
  - 不复制 a-stock-data 的实现，而是 AST 提取其 SKILL.md 中目标函数的定义（含依赖闭包），
    在隔离命名空间 exec，调用真实函数。
  - Vibe-Trading 回测 run_dir 遵循其 runner 约定：config.json + code/signal_engine.py。
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("NO_PROXY", "*")

# ---------------------------- Skill 定位 ----------------------------

_HOME = Path.home()

_SKILL_LOCATIONS = [
    _HOME / ".codex" / "skills",
    _HOME / ".claude" / "skills",
    _HOME / ".config" / "codex" / "skills",
]

# 港股/美股常见重仓名（用于提示 global-stock-data 穿透核验）
_HK_US_HINTS = [
    "腾讯控股", "阿里巴巴", "美团", "拼多多", "网易", "京东", "快手", "小米集团",
    "理想汽车", "蔚来", "小鹏汽车", "比亚迪股份", "百度集团", "哔哩哔哩", "中国移动",
    "英伟达", "苹果", "微软", "谷歌", "亚马逊", "特斯拉", "台积电", "阿斯麦", "礼来",
]

_VIBE_MCP_CANDIDATES = [
    _HOME / ".codex" / "mcp" / "vibe-trading" / "venv" / "Scripts" / "vibe-trading-mcp.exe",
    _HOME / ".codex" / "mcp" / "vibe-trading" / "venv" / "bin" / "vibe-trading-mcp",
]


def find_skill(name: str) -> Path | None:
    """在常见技能目录里定位 <name>/SKILL.md。"""
    for base in _SKILL_LOCATIONS:
        p = base / name / "SKILL.md"
        if p.exists():
            return p
    return None


def _python_blocks(skill_path: Path) -> list[str]:
    text = skill_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(r"```python\s*\n(.*?)```", text, flags=re.S)
    return [b.strip() for b in blocks if b.strip()]


# ---------------------------- AST 函数提取 ----------------------------

def _bound_names(node: ast.AST) -> list[str]:
    """Import 节点绑定的名字。"""
    names: list[str] = []
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            names.append(alias.asname or alias.name.split(".")[0])
    return names


def _assign_target_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                names.append(t.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.append(node.target.id)
    return names


def _is_constant_assign(node: ast.AST) -> bool:
    """模块级赋值（常量或安全初始化如 requests.Session()），统一收集进 defs。

    演示用赋值（d = board_fund_flow(...) 等）目标名通常是函数局部变量，
    _global_loads 的局部遮蔽分析会阻止它们进入闭包，因此这里不必再剔除 Call。
    """
    return isinstance(node, (ast.Assign, ast.AnnAssign))


def _locally_bound_names(func: ast.AST) -> set[str]:
    """函数/类体内所有局部绑定名（参数、赋值、for、with、import、except、推导式、walrus）。"""
    bound: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.arguments):
            for a in list(node.args) + list(node.kwonlyargs):
                if isinstance(a, ast.arg) and a.arg:
                    bound.add(a.arg)
            if node.vararg and isinstance(node.vararg, ast.arg):
                bound.add(node.vararg.arg)
            if node.kwarg and isinstance(node.kwarg, ast.arg):
                bound.add(node.kwarg.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update(_bound_names(node))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return bound


def _global_loads(func: ast.AST) -> set[str]:
    """函数体引用的全局名字（排除局部绑定后仍被 Load 的名字）。"""
    local = _locally_bound_names(func)
    out = set()
    for n in ast.walk(func):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in local:
            out.add(n.id)
    return out


def _extract_closure(blocks: list[str], targets: list[str]) -> tuple[str | None, str | None]:
    """从多个 python 代码块提取目标函数及其依赖闭包。

    Returns:
        (源码, 错误信息)。失败时源码为 None。
    """
    defs: dict[str, ast.AST] = {}
    order: list[str] = []
    for block in blocks:
        try:
            tree = ast.parse(block)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                key = node.name
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names = _bound_names(node)
                for n in names:
                    if n not in defs:
                        defs[n] = node
                        order.append(n)
                continue
            elif _is_constant_assign(node):
                names = _assign_target_names(node)
                for n in names:
                    if n not in defs:
                        defs[n] = node
                        order.append(n)
                continue
            else:
                continue
            if key not in defs:
                defs[key] = node
                order.append(key)

    missing = [t for t in targets if t not in defs]
    if missing:
        return None, f"SKILL.md 中未找到目标函数: {missing}"

    # BFS 依赖闭包（只看全局引用）
    needed = set(targets)
    queue = list(targets)
    while queue:
        cur = queue.pop()
        if cur not in defs:
            continue
        node = defs[cur]
        refs = _global_loads(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
            else _global_loads(node)
        for ref in refs:
            if ref in defs and ref not in needed:
                needed.add(ref)
                queue.append(ref)

    # 拓扑排序（常量/import 优先于引用它们的函数默认值）
    emitted: list[str] = []
    emitted_set: set[str] = set()

    def deps(name: str) -> list[str]:
        node = defs[name]
        refs = _global_loads(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
            else _global_loads(node)
        return [r for r in refs if r in needed]

    def visit(name: str) -> None:
        if name in emitted_set:
            return
        emitted_set.add(name)  # 防环
        for d in deps(name):
            if d in defs and d not in emitted_set:
                visit(d)
        if name not in emitted:
            emitted.append(name)

    for name in order:
        if name in needed and isinstance(defs[name], (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            visit(name)
    for name in order:
        if name in needed and isinstance(defs[name], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            visit(name)

    src = "\n\n".join(ast.unparse(defs[n]) for n in emitted)
    return src, None


def load_a_stock() -> dict:
    """加载 a-stock-data skill 的关键函数（尽力而为）。返回 {函数名: callable}。"""
    skill = find_skill("a-stock-data")
    if skill is None:
        return {"_error": "未安装 a-stock-data skill（~/.codex/skills/a-stock-data/SKILL.md）"}
    targets = [
        "board_fund_flow", "stock_fund_flow_120d", "daily_dragon_tiger",
        "dragon_tiger_board", "hsgt_realtime", "eastmoney_concept_blocks",
        "em_get", "norm_ticker", "get_prefix",
    ]
    src, err = _extract_closure(_python_blocks(skill), targets)
    if src is None:
        return {"_error": f"a-stock-data 提取失败: {err}"}
    try:
        ns: dict = {"__name__": "_a_stock_skill_", "__builtins__": __builtins__}
        exec(src, ns)  # noqa: S102 — 提取自本机已安装 skill，只定义函数/常量，不执行网络调用
    except Exception as e:  # noqa: BLE001
        return {"_error": f"a-stock-data 执行失败: {e!r}"}
    out = {t: ns[t] for t in targets if t in ns}
    if not out:
        return {"_error": "a-stock-data 提取后无可用函数"}
    # push2 实时域名被风控时，用 push2delay（延迟行情）同结构降级
    if "push2.eastmoney.com" in src:
        try:
            fb_ns: dict = {"__name__": "_a_stock_skill_fb_", "__builtins__": __builtins__}
            exec(src.replace("push2.eastmoney.com", "push2delay.eastmoney.com"), fb_ns)  # noqa: S102
            out["_fallback"] = {t: fb_ns[t] for t in targets if t in fb_ns}
        except Exception:  # noqa: BLE001
            pass
    return out


# ---------------------------- 资金面增强 ----------------------------

def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _pick_holdings(holdings) -> list[dict]:
    """从基金重仓 DataFrame 提取 [{name, code, weight}]，列名自适应。"""
    if holdings is None:
        return []
    try:
        import pandas as pd
        df = holdings if isinstance(holdings, pd.DataFrame) else pd.DataFrame(holdings)
    except Exception:
        return []
    if not len(df):
        return []
    code_col = next((c for c in df.columns if "代码" in str(c)), None)
    name_col = next((c for c in df.columns if "名称" in str(c)), None)
    weight_col = next((c for c in df.columns if "净值比例" in str(c) or "占净值" in str(c)), None)
    rows = []
    for _, r in df.head(10).iterrows():
        name = str(r.get(name_col, "")) if name_col else ""
        code = str(r.get(code_col, "")) if code_col else ""
        weight = _num(r.get(weight_col)) if weight_col else 0.0
        rows.append({"name": name, "code": code, "weight": weight})
    return [r for r in rows if r["name"] or r["code"]]


def _match_keywords(rows: list[dict], keywords: list[str]) -> list[dict]:
    """按关键词过滤板块资金流行（子串匹配，含去重）。"""
    seen = set()
    out = []
    for r in rows:
        name = str(r.get("name", ""))
        if any(k and k in name for k in keywords):
            key = (name, r.get("main_net"))
            if key not in seen:
                seen.add(key)
                out.append(r)
    return out


def enrich_capital_flow(code: str, sector_id: dict | None, holdings=None,
                        fund_name: str = "") -> dict:
    """用 a-stock-data 补齐板块/个股资金流 + 龙虎榜 + 北向，供报告展示。

    sector_id: sector_exposure.identify_sector 的输出（main_sector / matched_keyword）。
    """
    fns = load_a_stock()
    if not any(k in fns for k in ("board_fund_flow", "stock_fund_flow_120d")):
        return {"available": False, "source": "a-stock-data",
                "error": fns.get("_error", "a-stock-data 加载失败")}

    out: dict = {
        "available": True,
        "source": "a-stock-data",
        "as_of": datetime.now().strftime("%Y-%m-%d"),
    }
    fb = fns.get("_fallback", {})

    def call(name: str, *a, **k):
        try:
            return fns[name](*a, **k)
        except Exception:
            if name in fb:
                return fb[name](*a, **k)
            raise

    sid = sector_id or {}
    keywords = []
    for src in (sid.get("main_sector", ""), sid.get("matched_keyword", "")):
        if src and src not in keywords:
            keywords.append(src)
    keywords = [k for k in keywords if k]

    # 1) 板块资金流排名上下文（行业 + 概念，今日 + 5 日；a-stock-data 接口）
    try:
        bf = fns["board_fund_flow"]
        flow = {"industry": {}, "concept": {}}
        for bt in ("industry", "concept"):
            for period in ("today", "5d"):
                try:
                    d = call("board_fund_flow", bt, period, 80)
                    rows = d.get("rows", [])
                    flow[bt][period] = {
                        "total": d.get("total"),
                        "matched": _match_keywords(rows, keywords)[:8],
                        "top5": rows[:5],
                    }
                except Exception as e:  # noqa: BLE001
                    flow[bt][period] = {"error": f"{e!r}"}
        out["board_flow"] = flow
    except Exception as e:  # noqa: BLE001
        out["board_flow"] = {"error": f"{e!r}"}

    # 1.5) 板块定位 + 当日资金流（全量扫描，覆盖"净流出不在前80"的板块）
    try:
        scan = _scan_boards(fns, "industry")
        pick = _pick_board(scan, keywords)
        if pick is None:
            scan_c = _scan_boards(fns, "concept")
            pick = _pick_board(scan_c, keywords)
        if pick is not None:
            kline = _fflow_kline_today(fns, pick["code"])
            out["sector_board"] = {
                "board_type": "industry" if any(r.get("code") == pick["code"] for r in scan) else "concept",
                "board": pick,
                "today_flow": kline,
            }
    except Exception as e:  # noqa: BLE001
        out["sector_board"] = {"error": f"{e!r}"}

    # 2) 重仓股 120 日资金流（前 3 名）
    try:
        holds = _pick_holdings(holdings)
        out["holdings"] = holds[:10]
        sf = fns["stock_fund_flow_120d"]
        stock_flow = []
        for h in holds[:3]:
            if not h.get("code"):
                continue
            try:
                rows = call("stock_fund_flow_120d", h["code"])
                if isinstance(rows, list) and rows:
                    last = rows[-1]
                    stock_flow.append({
                        "name": h["name"], "code": h["code"], "weight": h["weight"],
                        "latest": {
                            "date": last.get("日期") or last.get("date") or last.get("d"),
                            "main_net": last.get("主力净流入-净额") or last.get("main_net") or last.get("f62"),
                            "main_pct": last.get("主力净流入-净占比") or last.get("main_pct") or last.get("f184"),
                        },
                    })
            except Exception as e:  # noqa: BLE001
                stock_flow.append({"name": h["name"], "code": h["code"], "error": f"{e!r}"})
        out["stock_flow"] = stock_flow
    except Exception as e:  # noqa: BLE001
        out["stock_flow"] = {"error": f"{e!r}"}

    # 3) 全市场龙虎榜（今日，筛选关键词/重仓）
    try:
        dt = call("daily_dragon_tiger")
        rows = dt.get("rows") or dt.get("data") or dt.get("stocks") or []
        holds = out.get("holdings", [])
        hold_names = [h.get("name", "") for h in holds]
        if isinstance(rows, list):
            normalized = []
            for r in rows:
                if isinstance(r, dict):
                    nm = r.get("名称") or r.get("name") or ""
                    normalized.append({"name": nm, **r})
            kw_matched = _match_keywords(normalized, keywords)[:8]
            hold_matched = [r for r in normalized if r.get("name") in hold_names][:8]
            out["dragon_tiger"] = {"total": dt.get("total") or dt.get("total_records"),
                                   "matched": kw_matched[:8], "holdings": hold_matched[:8]}
        else:
            out["dragon_tiger"] = {"note": "返回结构非预期"}
    except Exception as e:  # noqa: BLE001
        out["dragon_tiger"] = {"error": f"{e!r}"}

    # 4) 北向资金实时
    try:
        hs = call("hsgt_realtime")
        if hasattr(hs, "to_dict"):
            recs = hs.to_dict("records")
            out["northbound"] = {"rows": recs[-5:], "latest": recs[-1] if recs else None}
        else:
            out["northbound"] = {"raw": hs}
    except Exception as e:  # noqa: BLE001
        out["northbound"] = {"error": f"{e!r}"}

    # 5) 港股/美股重仓穿透提示
    out["global_stock_hint"] = global_stock_hint(holdings)

    return out



# ---------------------------- 板块定位（桥接自定义增强） ----------------------------

_BOARD_FS_MAP = {"industry": "m:90+t:2", "concept": "m:90+t:3", "region": "m:90+t:1"}


def _scan_boards(fns: dict, board_type: str = "industry") -> list[dict]:
    """全量扫描东财板块列表（按主力净额降序），返回 [{rank,name,code,change_pct,main_net,main_pct}]。

    走 push2delay（实时域名常被风控），分页 pz=100。失败返回空列表。
    """
    em_get = fns.get("em_get")
    if em_get is None:
        return []
    fs = _BOARD_FS_MAP.get(board_type)
    if fs is None:
        return []
    items = []
    for pn in range(1, 8):
        params = {"pn": str(pn), "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                  "fid": "f62", "fs": fs, "fields": "f12,f14,f3,f62,f184"}
        try:
            r = em_get("https://push2delay.eastmoney.com/api/qt/clist/get", params=params,
                       headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}, timeout=10)
            payload = r.json().get("data") or {}
            diff = payload.get("diff") or []
            total = int(payload.get("total") or 0)
        except Exception:  # noqa: BLE001
            break
        if not diff:
            break
        for it in diff:
            items.append({"name": it.get("f14", ""), "code": it.get("f12", ""),
                          "change_pct": it.get("f3", 0), "main_net": it.get("f62", 0),
                          "main_pct": it.get("f184", 0)})
        if len(items) >= total or len(diff) < 100:
            break
    for i, r in enumerate(items, 1):
        r["rank"] = i
    return items


def _fflow_kline_today(fns: dict, board_code: str) -> dict | None:
    """板块当日资金流K线（主力/超大/大/中/小单）。走 push2delay。"""
    em_get = fns.get("em_get")
    if em_get is None:
        return None
    params = {"lmt": "0", "klt": "101", "secid": f"90.{board_code}",
              "fields1": "f1,f2,f3,f7",
              "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"}
    try:
        r = em_get("https://push2delay.eastmoney.com/api/qt/stock/fflow/kline/get", params=params,
                   headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}, timeout=10)
        kl = (r.json().get("data") or {}).get("klines") or []
    except Exception:  # noqa: BLE001
        return None
    if not kl:
        return None
    parts = str(kl[-1]).split(",")
    if len(parts) < 6:
        return None
    return {
        "date": parts[0],
        "main_net": _num(parts[1]),
        "small_net": _num(parts[2]),
        "medium_net": _num(parts[3]),
        "large_net": _num(parts[4]),
        "super_large_net": _num(parts[5]),
    }


def _pick_board(scan: list[dict], keywords: list[str]) -> dict | None:
    """按关键词选板块：优先完整包含主板块名，其次匹配关键词且主力净额排序靠前。"""
    if not keywords:
        return None
    ranked = sorted(scan, key=lambda r: r.get("rank", 999))
    best = None
    for k in sorted(keywords, key=len, reverse=True):
        if not k:
            continue
        for r in ranked:
            name = str(r.get("name", ""))
            if k and k in name:
                score = 2 if name == k or name.startswith(k) else 1
                if best is None or score > best[0]:
                    best = (score, r)
        if best:
            return best[1]
    return None


def global_stock_hint(holdings) -> dict:
    """重仓含港股/美股时给出 global-stock-data 穿透核验提示。"""
    holds = _pick_holdings(holdings)
    matched = [h for h in holds if any(k in h.get("name", "") for k in _HK_US_HINTS)]
    if not matched:
        return {"available": False, "hits": []}
    return {
        "available": True,
        "source": "global-stock-data",
        "hits": matched,
        "advice": "重仓含港股/美股，建议用 global-stock-data skill 核验对应标的行情/财务/机构持仓后写入 agent_analysis.json。",
    }


# ---------------------------- Vibe-Trading 回测验证 ----------------------------

def find_vibe_mcp() -> Path | None:
    for p in _VIBE_MCP_CANDIDATES:
        if p.exists():
            return p
    return None


def _nav_to_ohlcv(nav) -> str:
    """净值序列 → Vibe-Trading local loader 的 CSV（open=high=low=close=unit_nav）。"""
    import pandas as pd
    df = nav.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["close"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df = df.dropna(subset=["close"])
    df["open"] = df["high"] = df["low"] = df["close"]
    df["volume"] = 0
    return df[["date", "open", "high", "low", "close", "volume"]].to_csv(index=False)


def _data_bridge_config_path() -> Path:
    return _HOME / ".vibe-trading" / "data-bridge" / "config.yaml"


def _upsert_bridge_config(code: str, csv_path: Path) -> None:
    """把基金代码映射到本地 CSV（写入 ~/.vibe-trading/data-bridge/config.yaml）。"""
    path = _data_bridge_config_path()
    entry = {
        "symbol": code,
        "type": "csv",
        "path": str(csv_path),
        "columns": {"date": "date", "open": "open", "high": "high", "low": "low",
                    "close": "close", "volume": "volume"},
        "date_format": "%Y-%m-%d",
    }
    try:
        import yaml
        cfg = {}
        if path.exists():
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sources = cfg.get("sources")
        if not isinstance(sources, list):
            sources = []
        sources = [s for s in sources if isinstance(s, dict) and str(s.get("symbol", "")) != code]
        sources.append(entry)
        cfg["sources"] = sources
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        # 无 pyyaml 时最小化写入（保留既有内容追加）
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
        if not any(f"symbol: {code}" in ln for ln in lines):
            lines.append("sources:")
            lines.append(f'  - symbol: "{code}"')
            lines.append("    type: csv")
            lines.append(f'    path: "{str(csv_path)}"')
        path.write_text("\n".join(lines), encoding="utf-8")


def _signal_engine_source(rightside: dict) -> str:
    """由 rightside.json 生成 Vibe-Trading signal_engine.py（右侧纪律 → 多空信号）。"""
    trailing = float((rightside or {}).get("trailing_stop_pct", 0.12) or 0.12)
    levels = {lvl.get("key"): lvl for lvl in (rightside or {}).get("levels", [])}
    stop = levels.get("stop", {}).get("price")
    tp3 = levels.get("tp3", {}).get("price")
    entry = levels.get("entry", {}).get("price")

    def _fmt(v) -> str:
        return f"{v:.6f}" if isinstance(v, (int, float)) and v else "0.0"

    return f'''"""fund-deep-analysis 右侧纪律信号引擎（由 run.py --vibe-backtest 自动生成）。

信号约定：1=持有多头，0=空仓。仅做多。
规则镜像 assets/right-side-rules.md：
  - 上升结构（close>MA20>MA60 且 MA20 上行）才持有；
  - 移动止盈：自持有以来峰值回撤 >{trailing * 100:.0f}% 离场；
  - 跌破 MA60 / 双轨止损位 / 高位止盈位 → 离场（信号归 0）。
"""
from typing import Dict

import pandas as pd


class SignalEngine:
    """右侧交易信号引擎。trailing_stop_pct 与 rightside.json 一致。"""

    def __init__(self, trailing_stop_pct: float = {trailing:.4f},
                 entry_ref: float = {_fmt(entry)}, stop_ref: float = {_fmt(stop)},
                 tp3_ref: float = {_fmt(tp3)}):
        self.trailing_stop_pct = float(trailing_stop_pct)
        self.entry_ref = float(entry_ref)
        self.stop_ref = float(stop_ref)
        self.tp3_ref = float(tp3_ref)

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        result = {{}}
        for code, df in data_map.items():
            close = df["close"].astype(float)
            ma20 = close.rolling(20).mean()
            ma60 = close.rolling(60).mean()
            ma20_up = ma20 > ma20.shift(1)
            uptrend = (close > ma20) & (ma20 > ma60) & ma20_up

            sig = pd.Series(0, index=df.index, dtype=int)
            holding = False
            peak = 0.0
            for i, dt in enumerate(df.index):
                c = close.iloc[i]
                if pd.isna(c) or pd.isna(ma60.iloc[i]):
                    continue
                if not holding and bool(uptrend.iloc[i]):
                    holding = True
                    peak = c
                if holding:
                    peak = max(peak, c)
                    exit_now = False
                    if self.trailing_stop_pct > 0 and peak > 0:
                        exit_now = exit_now or (c < peak * (1.0 - self.trailing_stop_pct))
                    if self.stop_ref > 0:
                        exit_now = exit_now or (c < self.stop_ref)
                    if self.tp3_ref > 0:
                        exit_now = exit_now or (c < self.tp3_ref)
                    if not exit_now and not bool(uptrend.iloc[i]) and c < ma20.iloc[i]:
                        exit_now = True
                    if exit_now:
                        holding = False
                sig.iloc[i] = 1 if holding else 0
            result[code] = sig
        return result
'''


def export_vibe_run(code: str, fund_name: str, rightside: dict, nav, run_root: Path) -> Path:
    """导出 Vibe-Trading 回测 run_dir（config.json + code/signal_engine.py + 本地数据映射）。

    返回 run_dir 路径。任何失败抛异常由调用方降级。
    """
    import pandas as pd

    run_root = Path(run_root).expanduser().resolve()
    run_dir = Path(run_root) / "vibe" / code
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "code").mkdir(parents=True, exist_ok=True)

    nav = nav.sort_values("date").reset_index(drop=True)
    start_date = pd.to_datetime(nav["date"]).min().strftime("%Y-%m-%d")
    end_date = pd.to_datetime(nav["date"]).max().strftime("%Y-%m-%d")

    data_dir = Path(run_root) / "vibe-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"{code}.csv"
    csv_path.write_text(_nav_to_ohlcv(nav), encoding="utf-8")
    _upsert_bridge_config(code, csv_path)

    config = {
        "codes": [code],
        "start_date": start_date,
        "end_date": end_date,
        "source": "local",
        "interval": "1D",
        "engine": "daily",
        "initial_cash": 1_000_000,
        "fund_name": fund_name,
        "note": "generated by fund-deep-analysis toolchain; data from local NAV OHLCV",
    }
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "code" / "signal_engine.py").write_text(
        _signal_engine_source(rightside), encoding="utf-8")
    return run_dir


class _MCPClient:
    """极简 MCP stdio JSON-RPC 客户端（只用于本机可信 vibe-trading-mcp）。"""

    def __init__(self, exe: Path, timeout: int = 900, env_extra: dict | None = None):
        self.exe = exe
        self.timeout = timeout
        self.env_extra = env_extra or {}
        self.proc = None

    def __enter__(self):
        env = {**os.environ, **self.env_extra}
        self.proc = subprocess.Popen(
            [str(self.exe)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=env,
        )
        return self

    def _send(self, obj: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _recv(self) -> dict:
        assert self.proc and self.proc.stdout
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout")
        return json.loads(line)

    def call(self, method: str, params: dict | None = None, timeout: int | None = None) -> dict:
        import queue
        import threading
        self._send({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        q: queue.Queue = queue.Queue()

        def _reader():
            try:
                q.put(self._recv())
            except Exception as e:  # noqa: BLE001
                q.put({"error": {"message": f"{e!r}"}})

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        try:
            return q.get(timeout=timeout or self.timeout)
        except queue.Empty:
            raise RuntimeError(f"MCP 调用超时（>{timeout or self.timeout}s）：{method}")

    def __exit__(self, *exc):
        try:
            if self.proc:
                self.proc.terminate()
        except Exception:  # noqa: BLE001
            pass


def run_vibe_backtest(run_dir: Path, timeout: int = 900) -> dict:
    """调用 vibe-trading-mcp 的 backtest 工具。返回解析后的 run card / 错误。"""
    run_dir = Path(run_dir).expanduser().resolve()
    exe = find_vibe_mcp()
    if exe is None:
        return {"available": False, "error": "未找到 vibe-trading-mcp（~/.codex/mcp/vibe-trading/venv）"}
    try:
        allowed = os.environ.get("VIBE_TRADING_ALLOWED_RUN_ROOTS", "")
        extra = {"VIBE_TRADING_ALLOWED_RUN_ROOTS": ",".join(
            x for x in [allowed, str(run_dir)] if x)}
        with _MCPClient(exe, timeout=timeout, env_extra=extra) as client:
            init = client.call("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "fund-deep-analysis", "version": "0.6"},
            }, timeout=120)
            if init.get("error"):
                return {"available": False, "error": f"initialize 失败: {init['error']}"}
            client._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            resp = client.call("tools/call", {
                "name": "backtest",
                "arguments": {"run_dir": str(run_dir)},
            }, timeout=timeout)
            if resp.get("error"):
                return {"available": False, "error": f"backtest 调用失败: {resp['error']}"}
            result = resp.get("result", {})
            content = result.get("content") or []
            texts = []
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(c.get("text", ""))
            raw = "\n".join(texts)
            try:
                parsed = json.loads(raw)
            except Exception:  # noqa: BLE001
                parsed = {"raw": raw[:8000]}
            if isinstance(parsed, dict):
                parsed["available"] = True
                parsed["source"] = "Vibe-Trading MCP"
                parsed["run_dir"] = str(run_dir)
                # 指标在 stdout 的 JSON 字符串里 → 平铺为 metrics 供报告渲染
                raw_stdout = parsed.get("stdout")
                if isinstance(raw_stdout, str):
                    try:
                        m = json.loads(raw_stdout)
                        if isinstance(m, dict):
                            parsed["metrics"] = m
                    except Exception:  # noqa: BLE001
                        pass
                return parsed
            return {"available": True, "source": "Vibe-Trading MCP", "run_dir": str(run_dir),
                    "result": parsed}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": f"Vibe-Trading 调用异常: {e!r}"}


# ---------------------------- 汇总 ----------------------------

def toolchain_status() -> dict:
    """供 --enrich-flow/--vibe-backtest 未显式开启时诊断用。"""
    return {
        "a_stock_skill": str(find_skill("a-stock-data")) if find_skill("a-stock-data") else None,
        "global_stock_skill": str(find_skill("global-stock-data")) if find_skill("global-stock-data") else None,
        "vibe_mcp": str(find_vibe_mcp()) if find_vibe_mcp() else None,
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(toolchain_status(), ensure_ascii=False, indent=2))
    fns = load_a_stock()
    print("a-stock 函数:", [k for k in fns if not k.startswith("_")])
    if "_error" in fns:
        print("ERROR:", fns["_error"])
