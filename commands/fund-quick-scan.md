---
description: 30秒快速分析基金——纯脚本出右侧作战卡+HTML（无消息面，适合速判）
argument-hint: "[基金代码，如 161725]"
---

# 基金快速分析

基金代码: $ARGUMENTS

快速模式（纯脚本，无 agent 介入，不出消息面）：
```
cd C:\Users\Administrator\.claude\skills\fund-deep-analysis\scripts && py run.py $ARGUMENTS --quick
```

读 `reports/$ARGUMENTS_<最新日期>/battle-card.md`，向用户汇报：
- 趋势状态（上升/震荡/下降）+ 板块共振信号灯
- 操作建议 + 仓位
- 关键净值位（建仓/加仓/止盈①②/移动止盈/止损，各带 status + 理由）
- 核心风险指标（最大回撤/夏普/距高点）

并打开 HTML 报告。
