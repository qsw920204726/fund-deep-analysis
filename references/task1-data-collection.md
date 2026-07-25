# Task 1 · 数据采集（akshare 基金接口）

## ⚠️ 网络坑（必读）

Windows 系统代理（IE 注册表）致 `push2.eastmoney.com` 等行情域名 SSL/连接失败。
**所有 lib 模块顶部 `os.environ["NO_PROXY"]="*"` 绕过系统代理。**

- `fund_*` 接口走 fund.eastmoney.com → 正常
- 指数/个股/板块行情走 push2.eastmoney.com → **不通**，改用**新浪源**

## 接口清单

### 基金接口（fund.eastmoney.com，正常）

| 用途 | 接口 | 备注 |
|---|---|---|
| 历史净值 | `fund_open_fund_info_em(symbol, period)` | 列：净值日期/单位净值/日增长率（**无累计净值**） |
| 重仓股 | `fund_portfolio_hold_em(symbol, date)` | date=年份（如"2024"），按季度披露 |
| 行业配置 | `fund_portfolio_industry_allocation_em(symbol, date)` | 证监会大类（制造业…），板块分析用处有限 |
| 基金经理 | `fund_manager_em()` | 全量返回，按代码过滤 |
| 基金名称/类型 | `fund_name_em()` | 全量字典（27000+ 只），`fetch_fund_name` 进程内缓存 |

### 板块/宽基指数（新浪源，绕开 push2）

```python
import akshare as ak
ak.stock_zh_index_daily(symbol="sz399997")  # 中证白酒
ak.stock_zh_index_daily(symbol="sh000300")  # 沪深300
```

返回 `[date, open, high, low, close, volume]`，symbol = `sz`/`sh` + 代码。

**行业指数**（见 `sector_exposure.SECTOR_INDEX_MAP`）：白酒 sz399997 · 银行 sz399986 · 券商 sz399975 · 医药 sh000933 · 食品饮料 sz399938 · 主要消费 sh000932 · 军工 sz399967 · 半导体 sz931865 · 新能源车 sz399976 · 光伏 sz931151 · 煤炭 sz399998 · 有色 sh000819 · 房地产 sz399393 · 电力 sz931559。

**宽基指数**（14 类，见 `sector_exposure.BROAD_BASE_INDEX`）：沪深300 sh000300 · 中证500 sh000905 · 中证800 sh000906 · 中证1000 sh000852 · 中证A500 sh932000 · 创业板指 sz399006 · 创业板50 sz399673 · 科创50 sh000688 · 上证50 sh000016 · 上证180 sh000010 · 深证100 sz399004 · 深证成指 sz399001 · 国证2000 sz399303 · 中证红利 sh000922。

## 关键注意

1. **无累计净值**：`fund_open_fund_info_em` 只返回单位净值。用 unit_nav 做趋势/回撤/波动（含分红基金总回报略低估，v2 补累计净值）。
2. **period 参数**实测返回全部历史（"近期"/"全部"都返回全部）。
3. **中文列名**：`data_fetcher.fetch_nav` 已用关键词容错映射成英文（date/unit_nav/daily_return）。
4. **日级 T+1**：最新净值是上一交易日收盘值，非实时。
5. **降级**：接口失败 → 重试 1 次 → 标注失败不编造；净值 < 60 条 → `run.py` 直接拒绝（趋势算不准）。
6. **板块识别不走个股行业接口**（stock_individual_info_em 走 push2 不通），改用基金名称 + 重仓股名称关键词匹配。
