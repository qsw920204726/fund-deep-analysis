---
description: 组合体检——多基金相关性+行业暴露重叠，防集中爆雷
argument-hint: "[代码1 代码2 代码3 ...] 至少2只"
---

# 组合体检

基金代码: $ARGUMENTS

跨基金检查组合隐性风险（防"单只都对、组合集中爆雷"）：
```
cd C:\Users\Administrator\.claude\skills\fund-deep-analysis\scripts && py lib/portfolio.py $ARGUMENTS
```

向用户汇报：相关性矩阵（高相关对 >0.7 = 同涨同跌）、行业暴露重叠、平均相关系数、风险提示。

重点提示**隐性集中**——如白酒 + 蓝筹精选看似不同（行业 vs 均衡），实际净值相关 0.7+（蓝筹重仓白酒），风险没真正分散。建议跨板块（消费+科技+金融+黄金）+ 低相关搭配。
