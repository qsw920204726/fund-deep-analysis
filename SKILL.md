---
name: fund-deep-analysis
description: Use when a user asks to analyze a Chinese fund (off-exchange OTC fund or on-exchange ETF), judge whether it can be bought or added to, inspect fund risk and sector resonance, or calculate right-side entry, take-profit, and stop-loss levels from a fund code. Supports both OTC funds (e.g. 161725) and on-exchange ETFs (e.g. 510300).
---

# 基金深度分析

## 核心原则

默认执行深度模式。把 Python 脚本视为所有净值位和指标的唯一数值来源；外部消息必须有日期与 URL，无法核验时明确降级，禁止凭记忆补写。

场外基金净值为日级 T+1；场内 ETF 有日K行情（前复权收盘价）及成交量。本 skill 只做日/周级中长线判断，不提供实时或日内交易建议。输出不是投资建议。

## 工作流

1. 从当前请求提取六位基金代码。缺失或格式错误时，只询问基金代码。
2. 以当前 `SKILL.md` 所在目录作为 `<skill-dir>`，不要猜测或硬编码安装路径。
3. 在当前可写工作区选择 `<runtime-dir>`。项目less任务优先使用 `<workspace>/outputs/fund-deep-analysis`，其他任务使用 `<workspace>/fund-deep-analysis-output`。不得写入或复制已安装的 skill 目录。
4. 选择能成功导入 `akshare`、`pandas` 和 `numpy` 的 Python 3.9+ 解释器。data_fetcher.is_etf() 自动识别场内 ETF / 场外基金并分流数据源。在 Windows 上忽略 `WindowsApps` 商店别名；找不到依赖时，给出使用 `<skill-dir>/scripts/requirements.txt` 的准确安装命令并说明需要安装，不要继续做残缺计算。
5. 运行：

   ```text
   <python> <skill-dir>/scripts/run.py <code> --stage1 --runtime-dir <runtime-dir>
   ```

6. 读取 `<runtime-dir>/.cache/<code>/rightside.json`、`sector.json`、`metrics.json` 和 `signals.json`。数据少于 60 个交易日时停止；不得绕过数据门控。
7. 用当前会话可用的网页搜索、浏览器或公共数据工具，检索主板块近 30-90 天的利好与利空。每条证据保留标题、日期、HTTP(S) URL、立场和摘要。优先使用监管披露、基金或指数官方资料、上市公司公告与可信财经媒体。
8. 用结构化 JSON 序列化写入 `<runtime-dir>/.cache/<code>/agent_analysis.json`。定性结论必须引用脚本中的净值、均线、回撤、夏普或其他风险数字；所有买卖净值位必须来自 `rightside.json`。
9. 无法核验外部消息时，使用 `evidence_status: unavailable`、空的 `bullish`、`bearish` 和 `sources`，并在 `summary` 与最终回复中说明限制。不得声称消息已核验。
10. 运行：

    ```text
    <python> <skill-dir>/scripts/run.py <code> --stage2 --runtime-dir <runtime-dir>
    ```

    除非用户明确要求打开报告，否则不要传 `--open`。

11. 返回操作建议、仓位、共振信号、关键净值位、核心风险、消息面与技术面的冲突判断、证据限制，以及 Markdown 和 HTML 报告的绝对路径。

## 决策纪律

- `regime=下降`：观望、不进场、仓位 0%；不得给出建仓或加仓净值位。
- 不得使用固定百分比、当前净值倍数或记忆中的价格替代脚本计算出的关键位。
- 消息面利好不等于买入；技术面下降时仍执行零仓位纪律。
- 不得把场外基金净值描述为实时价格。
- 不得在脚本失败后用常识补齐指标或交易位。

## Agent 分析契约

按 `assets/data-contracts.md` 写 `agent_analysis.json`。

- `verified`：至少包含一个结构化 `source`，每个 source 都有 `title`、`date`、`url`、`stance` 和 `summary`。
- `unavailable`：`sources`、`bullish`、`bearish` 必须为空，且 `summary` 明确说明证据不可用。
- `commentary`：引用 `rightside.json`、`metrics.json` 或 `signals.json` 的具体数字，说明当前是主升、反弹、震荡还是下降。

## 快速模式

只有用户明确要求快速、离线或不检索消息时，才运行：

```text
<python> <skill-dir>/scripts/run.py <code> --quick --runtime-dir <runtime-dir>
```

快速模式不得伪装成深度模式，必须说明未加入外部消息面。

## 参考资料

- 数据采集失败或降级：读 `references/task1-data-collection.md`
- 风险指标解释：读 `references/task2-risk-metrics.md`
- 右侧规则争议：读 `references/task5-right-side.md` 和 `assets/right-side-rules.md`
- JSON 字段：读 `assets/data-contracts.md`
