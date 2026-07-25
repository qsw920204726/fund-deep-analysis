# fund-deep-analysis · Claude Code 上下文（v0.4）

> 本文件供 Claude Code 自动读取，提供项目上下文。

## 这是什么

国内场外基金的**右侧交易决策** skill。用户说"分析基金 XXX / 这只基金能不能买 / 右侧"时触发 `SKILL.md`。

以**十年养基老手 + 右侧交易者**视角，结合基金净值趋势 + 板块（共振信号灯 + 消息面），输出右侧作战卡（建仓/加仓/止盈/止损净值位 + 理由 + 仓位）和 Bloomberg 风格 HTML 报告。

## 核心能力

| 能力 | 说明 |
|---|---|
| 右侧决策 | 建仓/加仓/止盈①②/移动止盈/止损，每个带 status（建议/不建议/若持有触发）+ reason（引用净值/均线/板块数字） |
| 板块共振 | 行业板块 + 宽基（14类）+ 均衡三类识别；基金 vs 板块/大盘指数双 regime → 🟢🟡🔴⚪ |
| 板块消息面 | agent 用 WebSearch 搜主板块最新利好/利空，分类总结（深度模式） |
| 风险指标 | 最大回撤/年化波动/夏普/卡玛/索提诺 + 多周期收益 |
| HTML 报告 | Bloomberg 深色，净值曲线 SVG + hover + 净值位卡片 + 消息面双栏，单文件可分享 |

## 环境（重要）

- **Python**：用 `py` 启动器（3.13.2）。`python` 命令被 Windows Store 别名拦截，**一律用 py**。
- **依赖**：`py -m pip install -r scripts/requirements.txt`（akshare + pandas）
- **网络坑**：Windows 系统代理（IE 注册表）致 `push2.eastmoney.com` 连接失败。所有 lib 模块顶部 `os.environ["NO_PROXY"]="*"` 绕过。fund_* 走 fund.eastmoney.com 正常；板块/宽基指数走**新浪源** `stock_zh_index_daily`。
- **中文乱码**：run.py 已 reconfigure utf-8；手动跑单模块加 `PYTHONIOENCODING=utf-8`。

## 用法

```bash
cd C:\Users\Administrator\.claude\skills\fund-deep-analysis\scripts
py run.py 161725 --quick      # 30-60秒，纯脚本出作战卡+HTML（无消息面）
py run.py 161725              # 深度模式：stage1 后停，agent 介入搜消息面+写判断，再 stage2
```

新会话直接说"分析基金 161725"自动触发 skill。

## 核心模块（scripts/lib/）

| 模块 | 职责 |
|---|---|
| `data_fetcher.py` | akshare 封装（净值/重仓/行业/经理/基金名称） |
| `risk_metrics.py` | 净值→回撤/波动/夏普/卡玛/索提诺 |
| `trend_signals.py` | 周线 20/60 + 日线趋势信号 |
| `right_side_engine.py` | **右侧决策引擎（灵魂）** + 作战卡渲染 |
| `sector_exposure.py` | 板块识别（行业/宽基/均衡） |
| `sector_resonance.py` | 板块指数走势 + 共振信号灯 |
| `report_render.py` | Bloomberg 深色 HTML 报告 |

## 数据流转

```
raw_data.json → metrics.json → signals.json → sector.json → rightside.json
                                                       ↓
                                       [agent_analysis.json]  ← agent 介入（commentary + sector_news）
                                                       ↓
                         reports/{code}_{date}/battle-card.md + report.html
```

## 阶段状态

- ✅ Phase 0-1：净值→风险→右侧作战卡（MVP）
- ✅ Phase 2：板块联动（共振信号灯 + 消息面）
- ✅ HTML 报告（Bloomberg 深色）+ 操作位理由
- ✅ 宽基识别（14类）
- ⏳ Phase 3（待续）：slash 命令 / 基金经理画像 / 多基金对比 / 筛选 / self-review gate
- ⏳ v2：Brinson 业绩归因 / 场内 ETF / 累计净值

实现计划详见 `C:\Users\Administrator\.claude\plans\glistening-enchanting-hare.md`。
