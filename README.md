# fund-deep-analysis · 基金右侧交易决策 skill

> 一个 [Codex](https://github.com/openai/codex) skill。以**十年养基老手 + 右侧交易者**视角，分析国内基金（场外 OTC 基金 / 场内 ETF），结合基金净值趋势 + 板块（共振 + 消息面），输出**右侧作战卡**：建仓/加仓/止盈/止损的具体净值位 + 理由 + 仓位。

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)

## 这是什么

不是通用基金分析工具，而是**右侧交易决策工具**。整个分析只回答一个问题：

> **这只基金现在该不该动手、怎么动手。**

基于 [akshare](https://github.com/akfamily/akshare) 数据，周线为主、日线辅助的中长线趋势跟踪。支持场外基金（如 161725）和场内 ETF（如 510300）。

## 核心能力

| 能力 | 说明 |
|---|---|
| 🎯 右侧作战卡 | 建仓/加仓/止盈①②/移动止盈/止损，每个带 **status（建议/不建议/若持有触发）+ 理由**（引用净值/均线/板块数字） |
| 📊 板块共振 | 行业板块 + 宽基(14类) + 均衡三识别；基金 vs 板块/大盘双 regime → 🟢🟡🔴⚪ |
| 📰 板块消息面 | agent 用网页搜索检索主板块最新利好/利空，分类总结（深度模式） |
| 📈 风险指标 | 最大回撤 / 年化波动 / 夏普 / 卡玛 / 索提诺 + 多周期收益 |
| 🌐 HTML 报告 | Bloomberg 深色风，净值曲线 SVG + hover、净值位卡片、消息面双栏，单文件可分享 |
| 🔬 历史回测 | 右侧信号在该基金的历史胜率 / 收益（防盲信未验证信号） |
| 💰 估值锚 | 宽基 PE 历史分位（防技术面高位接盘；行业基金数据源受限降级） |
| 🧩 组合体检 | 多基金相关性 + 行业暴露重叠（防单只都对、组合集中爆雷） |

## 效果示例（159531 中证2000ETF南方 · 2026-08-03）

```
当前净值: 1.301   趋势: 震荡（多头排列）

▶ 操作建议: 观望 · 等待信号        建议仓位: 0%
> 震荡无明确右侧信号（缺突破或更高低点）。备选关注位：站稳 20 周线。

🎯 关键净值位（含理由）
建仓    暂不建议   1.491   关注位 MA20，站稳 + 企稳结构出现再议
加仓    不建议     —       趋势为「震荡」、无上升结构，加仓 = 接飞刀
止盈①   若持有触发 1.2825  跌破 MA5d/MA10d 说明短线走弱，先减 30%
移动止盈 若持有触发 1.4291  从阶段高点 1.624 回撤 12% 触发
止损    若持有触发 1.494   跌破前低 → 更低低点，坚决清仓

📰 板块消息面（中证2000/小盘股）
🔼 利好: 机构预测 2026 年净利润复合增速 53.94%，聪明钱净流入小盘
🔽 利空: Q2 仅涨 5.99% 跑输其他宽基，重仓成分股矩阵股份/利通电子连续大跌
💡 消息面偏多 vs 技术面偏弱 = 矛盾，纪律上零仓位，等右侧确认
```

## 快速开始

### 1. 安装

```bash
git clone https://github.com/qsw920204726/fund-deep-analysis.git
# 放到 Codex skills 目录：
#   Mac/Linux: ~/.codex/skills/fund-deep-analysis
#   Windows:   C:\Users\<你>\.codex\skills\fund-deep-analysis

cd fund-deep-analysis/scripts
pip install -r requirements.txt        # Windows 用 py -m pip
```

### 2. 用法

**自然语言**（在 Codex 中新开会话，skill 自动触发）
```
分析基金 161725
这只白酒基金现在能加仓吗
场内 159531
```

**直接跑脚本**（跑完自动打开 HTML，加 `--no-open` 跳过）
```bash
cd scripts
py run.py 161725 --quick         # 快速出作战卡 + HTML（自动打开）
py run.py 161725                 # 深度：--stage1 → agent 介入 → --stage2
py lib/portfolio.py 161725 005827 110023   # 组合体检（多基金相关性 + 集中度）
```

## 工作原理

**两段式架构**（数据靠脚本，判断靠 agent）：

```
stage1 脚本:  净值 → 风险指标 → 周线趋势 → 板块共振 → 骨架决策
                                  ↓
agent 介入:   读骨架 → 网页搜索板块消息面 → 写定性研判
                                  ↓
stage2 脚本:  合并 agent 分析 → 右侧作战卡 + HTML 报告
```

**板块分析三层**：
- 🔧 技术面：基金 regime + 板块/大盘 regime → 共振信号灯
- 📰 消息面：agent 搜主板块最新利好/利空
- 🧠 研判：消息面 vs 技术面矛盾分析

## 右侧交易铁律

1. **下降趋势绝不进场** —— regime=下降 时硬编码仓位 0%，不给建仓/加仓净值位（右侧第一条纪律，写在 `right_side_engine.decide()` 里）
2. **消息面利好 ≠ 买入** —— 盈利预期/机构看好不等于即时入场，技术面下降时仍执行零仓位纪律
3. **关键位只认脚本算的** —— 禁用固定百分比、当前净值倍数或记忆价格替代 `rightside.json` 的净值位
4. **止盈止损始终给** —— 即使不进场，已持有者要知道在哪撤：①跌破 5/10 日线减 30% → ②跌破 20 周线减 40% → ③跌破 60 周线清仓；**移动止盈从阶段高点回撤 12% 清仓**
5. **深度回撤警惕飞刀** —— 距阶段高点 < -25% 标记"深度回撤"警告
6. **分批进、分批出** —— 建仓底仓 40%→主升确认补满仓 100%；加仓金字塔 40→35→25%（越加越少）；止损坚决清仓

> 参数定值详见 `assets/right-side-rules.md`，决策逻辑详见 `references/task5-right-side.md`。

## 目录结构

```
fund-deep-analysis/
├── SKILL.md                  # 入口（Codex skill 规范）
├── agents/openai.yaml        # Codex skill 接口定义
├── scripts/
│   ├── run.py                # 两段式入口（--quick / --stage1 / --stage2）
│   ├── requirements.txt
│   └── lib/                  # 核心模块
│       ├── data_fetcher.py        # akshare 封装（自动识别场内 ETF / 场外基金）
│       ├── risk_metrics.py        # 回撤/波动/夏普/卡玛
│       ├── trend_signals.py       # 周线 20/60 + 日线趋势
│       ├── right_side_engine.py   # ★ 右侧决策引擎（灵魂）
│       ├── sector_exposure.py     # 板块识别（行业/宽基/均衡）
│       ├── sector_resonance.py    # 板块共振信号灯
│       ├── report_render.py       # Bloomberg HTML 报告
│       ├── backtest.py            # 历史回测（信号胜率）
│       ├── valuation.py           # 估值锚（PE 分位）
│       └── portfolio.py           # 组合体检（相关性 / 集中度）
├── references/               # 按需加载的方法论
├── assets/                   # 参数定值 + 数据契约 + 免责
└── reports/                  # 生成报告（运行产物，已 gitignore）
```

## ⚠️ 免责

本 skill 输出的是**右侧交易策略框架的机械信号 + agent 研判，非投资建议**。场外基金 T+1、净值滞后，信号仅供决策参考，盈亏自负。**投资有风险，入市需谨慎。**

## License

[MIT](LICENSE)