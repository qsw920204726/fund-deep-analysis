---
name: fund-deep-analysis
description: 国内场外基金右侧交易决策工具。当用户提到"分析基金 / 基金代码 / 右侧交易 / 建仓加仓 / 止盈止损 / 这只基金现在能不能买 / 养基 / 基金体检"等请求时触发。以十年养基老手+右侧交易者视角，基于基金净值趋势（akshare 数据），输出右侧作战卡：建仓/加仓/止盈/止损的具体净值位 + 仓位建议 + 风险指标。周线为主、日线辅助的中长线趋势跟踪。关键词：基金、场外基金、右侧交易、建仓、加仓、止盈、止损、净值、最大回撤、夏普、卡玛、akshare、养基。
license: MIT
compatibility: 需要 Python 3.9+（Windows 用 `py` 启动器，`python` 命令被 Store 别名拦截）、akshare + pandas（`py -m pip install -r scripts/requirements.txt`）。Windows 系统代理可能致 push2.eastmoney.com 行情域名连接失败，脚本已内置 NO_PROXY=* 绕过；板块/宽基指数走新浪源 stock_zh_index_daily。
metadata:
  version: "0.4.0"
  author: "user"
---

# 基金右侧交易决策 · 深度分析工作流 v0.4

> 你正在扮演一位 **十年养基老手 + 右侧交易者**。
> 脚本负责算净值 / 风险 / 趋势 / 信号，你负责定性判断和叙事。
> 整个分析只回答一个问题：**这只基金现在该不该动手、怎么动手。**

## ⚠️ 硬约束（必须如实告知用户）

**场外基金净值是日级 T+1、没有实时价格。** 因此右侧交易只能做 **日/周级中长线趋势跟踪**，不能做日内/分钟级择时。用户若要精细择时，需场内 ETF（Phase 4 支持）。

## 🎯 右侧铁律（违反即失格）

1. **不抄底、不猜顶** —— 趋势确认才动手
2. **宁可买贵 5%，不接飞刀**
3. **分批进、分批出** —— 永远不满仓一把梭
4. **止损要快（错了就跑），止盈用移动止盈让利润奔跑**

## 🔧 执行方式

### 快速模式（默认，30 秒出卡）
```bash
cd <skill_dir>/scripts
py run.py <基金代码> --quick
```
一把跑完 stage1 + stage2，直出作战卡（纯脚本，无 agent 介入）。适合速判。

### 深度模式（两段式，agent 介入做定性判断）
```bash
py run.py <基金代码>      # 跑 stage1，停在介入点
```
1. **stage1 脚本**：采集净值 → 算风险指标 → 算趋势信号 → 骨架决策 → 写 `.cache/{code}/rightside.json`
2. **🧠 你介入**（`<HARD-GATE>` 见下）：读 `rightside.json`，结合板块前景 / 风格漂移 / 是否主升浪做定性判断，写 `.cache/{code}/agent_analysis.json`（含 `commentary` 字段）
3. **stage2 脚本**：读 `agent_analysis.json` 合并，出作战卡

## ⛔ HARD-GATE（脚本与指令双层）

1. **数据不足门控**（脚本强制）：净值 < 60 个交易日 → `run.py` 直接 raise，拒绝分析（新基金数据不够算趋势）。
2. **下降趋势纪律**（脚本+指令）：`regime=下降` 的基金，作战卡必须标 **"观望 · 不进场，仓位 0%"**，建仓/加仓位显示 `—`。**绝不为下跌标的给建仓位**——这是右侧第一条纪律。
3. **禁止编造**（指令）：作战卡所有净值位必须来自脚本 `rightside.json`，定性判断必须引用具体净值位/回撤/夏普数字。
4. **禁止废话**（指令）：agent 定性研判禁用"基本面良好 / 值得关注 / 前景广阔"——每句必须带数字或有冲突感的判断。
5. **板块识别覆盖（已接入 Phase 2）**：① 行业板块（白酒/医药/银行/半导体/新能源/军工/券商/有色等，靠基金名称 + 重仓股集中度识别）② **宽基**（沪深300/中证500/创业板/科创50/上证50/中证1000/深证成指/中证红利等 14 类，有跟踪指数做共振）③ 主动均衡型诚实标"未识别"。板块共振信号灯 + 消息面都已实装。

## 📋 数据流转（参照 stock-deep-analyzer 的 .cache 模式）

```
raw_data.json → metrics.json → signals.json → rightside.json
                                                    ↓
                                    [agent_analysis.json]  ← agent 介入写入
                                                    ↓
                          reports/{code}_{date}/battle-card.md
```

每个文件由谁写、谁读、字段 schema 详见 `assets/data-contracts.md`。

## 📚 参考文档（用到才读，避免一次性加载）

- `references/task1-data-collection.md` — akshare 基金接口清单 + 抓取/降级
- `references/task2-risk-metrics.md` — 风险收益指标公式
- `references/task5-right-side.md` — 右侧决策系统详解（四时机信号体系）
- `assets/right-side-rules.md` — 右侧参数定值（周线/止盈阈值）
- `assets/data-contracts.md` — 所有 JSON schema 契约

## 📊 核心产物：右侧作战卡

一张卡回答"该不该动手"：趋势状态 + 操作建议（观望/试探/持有/加仓）+ 建仓/加仓/止盈①②③/移动止盈/止损 的具体净值位 + 建议仓位 + 风险指标（回撤/波动/夏普/卡玛）+ 板块信号灯。

## 🧠 Agent 介入写什么（深度模式）

读 `rightside.json` 后，在 `agent_analysis.json` 写：
- `commentary`：定性研判——这只基金**当下**的右侧判断。结合：是否在主升浪（vs 反弹）、风格是否漂移、深跌标的的风险、当前净值位相对均线/前低的位置。**必须引用 rightside.json 里的具体数字。**
- `sector_news`：**主板块最新利好/利空消息面**。用 WebSearch 搜「{主板块}板块 最新 利好 利空 {年}」（主板块见 `sector.json` 的 `sector_id.main_sector`），分类写入 `sector`/`as_of`/`bullish[]`/`bearish[]`/`summary`。**关键纪律：消息面利好 ≠ 立即买入**——必须和技术面右侧信号结合判断（消息面利好但技术面下降 = 飞刀，仍不抄底）。`--quick` 模式无 agent，消息面留空。
- 可选 `action_override` / `entry_override`：仅当脚本机械决策明显不合理时覆盖（如板块见顶预警下，即便基金 regime=上升 也降仓）。

**记住：你是养基老手，不是脚本运行器。脚本是你的算盘，判断和纪律是你的。**
