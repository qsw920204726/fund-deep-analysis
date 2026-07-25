---
description: 深度分析一只场外基金——右侧作战卡 + 板块共振 + 消息面 + HTML 报告（agent 介入搜板块消息）
argument-hint: "[基金代码，如 161725]"
---

# 基金深度分析

基金代码: $ARGUMENTS

按 `C:\Users\Administrator\.claude\skills\fund-deep-analysis\SKILL.md` 的**深度模式**执行：

1. **stage1**（采集净值+风险+趋势+板块，停在 agent 介入点）：
   ```
   cd C:\Users\Administrator\.claude\skills\fund-deep-analysis\scripts && py run.py $ARGUMENTS --stage1
   ```

2. **agent 介入**：读 `.cache/$ARGUMENTS/rightside.json` + `sector.json`：
   - 用 WebSearch 搜主板块（`sector_id.main_sector`；若为宽基则搜大盘/宏观）最新利好/利空（近 1-2 月）
   - 写 `.cache/$ARGUMENTS/agent_analysis.json`：
     - `commentary`：定性研判，**引用 rightside.json 具体数字**（净值/均线/回撤）
     - `sector_news`：`{sector, as_of, bullish[], bearish[], summary}`
   - **铁律**：消息面利好 ≠ 买入，须结合技术面右侧（消息面利好+技术面下降=飞刀不抄底）

3. **stage2**（合并 agent 分析，出报告）：
   ```
   py run.py $ARGUMENTS --stage2
   ```

4. 向用户汇报：操作建议 + 仓位、板块共振信号灯、消息面利好/利空与矛盾研判，并打开 HTML 报告。
