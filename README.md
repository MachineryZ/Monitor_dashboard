# 🚀 Futures Monitor Dashboard

> 商品期货（CNCF）+ 股指期货（CNIF）多产品实时监控仪表板

---

## 一、项目简介

Futures Monitor Dashboard 是一个基于 **Streamlit** 的期货交易监控仪表板，用于实时展示多个产品（策略）的账户资金、持仓、盈亏、风险敞口与当日交易统计。覆盖 **7 个产品**，横跨 **商品期货（cncf）** 与 **股指期货（cnif）** 两个市场，分别对接 **东正（dz）** 和 **中信（zx）** 两家券商。

核心能力：

| 能力 | 说明 |
|------|------|
| 多产品聚合 | 7 个产品在同一界面横向对比 |
| 资金流监控 | balance / pre_balance / bank / 净入出金 |
| 持仓明细 | 每合约的 long/short 持仓、市值、盈亏 |
| 风险预警 | max_margin / product_low_limit 阈值告警 |
| 交易统计 | 当日 8 列交易指标（4 类开/平 × 手数+市值） |
| 银行账户对接 | 通过 RWP API 拉取基金单元 total_asset |
| 告警通知 | 阈值触发 → 企业微信 Webhook |
| 状态指示 | 红色 / 黄色圈圈直观呈现异常等级 |

---

## 二、技术栈

- **Python 3.x**
- **Streamlit** —— Web UI
- **pandas / numpy** —— 数据处理
- **rwp_api** —— 银行账户资产查询
- **clickhouse-connect** —— Clip / Uplimit 系数查询
- **requests** —— 企业微信 Webhook 告警

---

## 三、文件 / 数据源依赖

| 文件 / 接口 | 路径 / 来源 | 用途 |
|------------|------------|------|
| `account_info_{date}.csv` | 各产品路径下 | 账户余额、保证金、手续费 |
| `position_data_{date}.csv` | 各产品路径下 | 持仓明细（多/空） |
| `trade_data_{date}.csv` | 各产品路径下 | 当日成交明细（用于 8 列统计） |
| `order_data_{date}.csv` | 各产品路径下 | 委托明细（备用） |
| `ins_static_info.csv` | `/cpfs/rawdata/{cncf,cnif}_all_need_before_open/` | 合约乘数、交易所 |
| `partial_market_data_realtime/{commodity,futures}/{date}.csv` | NFS 共享盘 | 实时行情（ask/bid → 中间价） |
| `margin_uplimit_*.csv` | `/cpfs/rawdata/{cncf,cnif}_all_need_before_open/` | 保证金率 / 限额 |
| `prod_log/china_future/{cncf,cnif}/{strategy}/{date}.csv` | 策略运行日志 | 目标仓位（risk_position） |
| `/cpfs/intrastats/calendar` | 系统共享 | 交易日历 |
| `commodity_meta.product_clip` | ClickHouse | 单产品 Clip |
| `commodity_meta.product_uplimit_coef` | ClickHouse | Uplimit 系数 |
| RWP API | `rwp_api.get_unit_asset_chart` | 银行账户 total_asset |
| WeChat Webhook | 企业微信机器人 | 阈值告警 |

---

## 四、全局常量与配置

### 4.1 RWP API 凭据

```python
RWP_CREDENTIALS = {
    "username": "jiangl",
    "password": "666666@dunhe",
}
```

### 4.2 产品 ↔ 银行账户映射

通过 `PRODUCT_BANK_MAPPING` 把产品 NFS 路径映射到 RWP API 的 `(fund_id, unit_id)`，决定调用哪个基金单元接口获取银行账户余额。

| 产品路径 | fund_id | unit_id | 备注 |
|---------|--------:|--------:|------|
| `commodity_trade_data_baguatian` | 58 | 230 | 八卦田（硬编码） |
| `commodity_trade_data_shjq_zx` | 569 | 9118 | 山海 CTA 平衡1号（RWP 实时） |
| `commodity_trade_data_shph1h_zx` | 568 | 9122 | 进取（RWP 实时） |
| `commodity_trade_date` | 215 | 1049 | zz1h（硬编码） |
| `cnif_trade_data_jz1h` | 319 | 1604 | 硬编码 |
| `cnif_trade_data_ly1h` | 34 | 216 | 硬编码 |
| `cnif_trade_data_zz1h` | 215 | 1049 | 硬编码 |

> fund_id ∈ {569, 568} 时调用 RWP 实时接口；其余 fund_id 取硬编码常量。

### 4.3 交易时段

| 市场 | 上午 | 下午 | 夜盘 |
|------|------|------|------|
| **CNCF（商品期货）** | 09:00–10:15 / 10:30–11:30 | 13:30–15:00 | **21:00–次日 02:30**（跨午夜） |
| **CNIF（股指期货）** | 09:30–11:30 | 13:00–15:00 | 无 |

### 4.4 产品配置 `PRODUCT_CONFIGS`

每个产品的核心字段：

| 字段 | 含义 | 示例 |
|------|------|------|
| `path` | NFS 数据目录 | `/mnt/nfs_bohr_data1/.../cnif_trade_data_jz1h` |
| `broker` | 券商 | `dz`（东正） / `zx`（中信） |
| `product` | 策略代码 | `bgt_ax1h` / `shjq` / `shph1h` / `zz1h` / `jz1h` / `ly1h` |
| `market` | 市场 | `commodity` / `futures` |
| `init_capital` | 初始资金（兜底） | 0 |
| `aum_mul` | AUM 倍数 | `4.0` / `5.0` / `4.7858` |
| `aum_formula` | AUM 自定义公式（lambda） | `lambda pb, bal: 25_000_000 + (bal - 6_000_000)` |
| `db_product` | ClickHouse product_clip 查询 key | `commodity_melt_bgt` / `None` |

**AUM 解析优先级**（`resolve_init_capital`）：
1. `aum_formula`（如存在，调用之）
2. `pre_balance × aum_mul`（如 `aum_mul` 存在）
3. `init_capital`（兜底）
4. `pre_balance`（最终兜底）

---

## 五、变量定义

### 5.1 Summary 表字段（Overview）

| 字段 | 分类 | 类型 | 计算 / 来源 | 说明 |
|------|------|------|------------|------|
| `market` | 市场 | str | `cncf` / `cnif` | 市场标识 |
| `product` | 市场 | str | `cfg["product"]` | 策略代码 |
| `broker` | 市场 | str | `dz` / `zx` | 券商代码 |
| `init_capital` | 资金 | float | `resolve_init_capital()` | AUM / 策略规模 |
| `balance` | 资金 | float | `account_info.balance` | 当前账户余额 |
| `pre_balance` | 资金 | float | `account_info.pre_balance` | 前日余额（资金基数） |
| `bank` | 资金 | float | RWP API `total_asset` | 银行账户余额 |
| `market_value` | 持仓 | float | `Σ price × qty × multiplier` | 当前持仓总市值 |
| `cost` | 资金 | float | `account_info.fee` | 累计手续费 |
| `net_return` | 资金 | float | `Σ position_profit + close_profit − fee` | 净收益 |
| `fee` | 资金 | str (%) | `cost / init_capital × 100%` | 手续费占比 |
| `pnl` | 资金 | str (%) | `net_return / init_capital × 100%` | 收益率 |
| `max_margin` | 风险 | float | `max(单合约保证金) / balance` | **> 25% 告警** |
| `product_low_limit` | 风险 | float | `market_value / balance` | **< 0.8 告警**（ly1h 例外） |
| `margin` | 风险 | float | `account_info.curr_margin` | 当前占用保证金 |
| `margin_ratio` | 风险 | str (%) | `margin / pre_balance × 100%` | 保证金占用比 |
| `update_time` | 时间 | str | 各 csv 中 `update_time` 最大值 | 最后一次数据更新时间 |
| `time` | 时间 | str | 系统时间 | 仪表板查询时刻 |
| `deposit_withdraw` | 资金 | float | `deposit − withdraw` | 净入出金 |
| `warnings` | 系统 | str | 累计警告信息 | 异常描述 |
| `is_market_open` | 系统 | bool | 交易时段判断 | 是否处于开市时段 |
| `is_position_empty` | 系统 | bool | `position_data` 是否仅有 header | **新增**：清仓标记 |

### 5.2 交易统计 8 列 + 4 Ratio（Overview 字段）

从 `trade_data_{date}.csv` 的 `direction` 与 `offset_flag` 字段聚合。

**编码说明**：

| 字段 | 取值 | 含义 |
|------|------|------|
| `direction` | 66 (`B`) | 买 |
| `direction` | 83 (`S`) | 卖 |
| `offset_flag` | 79 / 48 / 0 | 开仓（Open） |
| `offset_flag` | 67 | 平仓（Close） |
| `offset_flag` | 68 | 平今（CloseToday） |

| 字段 | 分类 | 类型 | 公式 |
|------|------|------|------|
| `BuyOpenNumber` | 交易统计 | int | `Σ volume (dir=66, flag∈{79,48,0})` |
| `BuyOpenMarketValue` | 交易统计 | float | `BuyOpenNumber × price × multiplier` |
| `BOMVRatio` | 交易统计 | float | `BuyOpenMarketValue / init_capital` |
| `BuyCloseNumber` | 交易统计 | int | `Σ volume (dir=66, flag∈{67,68})` |
| `BuyCloseMarketValue` | 交易统计 | float | `BuyCloseNumber × price × multiplier` |
| `BCMVRatio` | 交易统计 | float | `BuyCloseMarketValue / init_capital` |
| `SellOpenNumber` | 交易统计 | int | `Σ volume (dir=83, flag∈{79,48,0})` |
| `SellOpenMarketValue` | 交易统计 | float | `SellOpenNumber × price × multiplier` |
| `SOMVRatio` | 交易统计 | float | `SellOpenMarketValue / init_capital` |
| `SellCloseNumber` | 交易统计 | int | `Σ volume (dir=83, flag∈{67,68})` |
| `SellCloseMarketValue` | 交易统计 | float | `SellCloseNumber × price × multiplier` |
| `SCMVRatio` | 交易统计 | float | `SellCloseMarketValue / init_capital` |

### 5.3 Per-Instrument Detail 表字段

每个产品 expander 内的子表，按合约 × 多空方向一行展示。

| 字段 | 类型 | 计算 / 来源 | 说明 |
|------|------|------------|------|
| `instrument` | str | `position_data.instrument_id` | 合约代码（如 `rb2501`） |
| `market_value` | float | `price × qty × multiplier` | 该方向该合约市值 |
| `position` | int | `position_data.position`（LONG 为正，SHORT 为负） | 当前持仓数 |
| `yd_position` | int | `position_data.yd_position` | 昨仓 |
| `today_position` | int | `position_data.today_position` | 今仓 |
| `risk_position` | int / None | 策略日志中的 `value` | 目标仓位 |
| `clip` | int / None | ClickHouse `product_clip` | 单产品 Clip |
| `uplimit` | float / None | `up_limit_holding_position × coef` | 持仓上限 |
| `position_type` | str | `LONG` / `SHORT` / `NONE` | 持仓方向 |
| `close_profit` | float | `position_data.close_profit` | 平仓盈亏 |
| `position_profit` | float | `position_data.position_profit` | 持仓盈亏 |
| `total_pnl` | float | `close_profit + position_profit` | 当日盈亏 |
| `instrument_margin` | float | `price × qty × multiplier × margin_ratio` | 占用保证金（SHORT 为 0） |
| `exchange` | str | `ins_static_info.exchange` | 交易所 |
| `last_trade_time` | str | `trade_data` 中该合约最后成交时间（按 21:00 切日调整） | 最后成交时间 |
| `risk_match` | str | `long − short == risk_position ? "matched" : "red"` | **红色不匹配** |
| `BuyOpenNumber` ~ `SellCloseMarketValue` | – | 同 5.2 公式（按合约过滤） | 8 列交易统计 |

---

## 六、异常指示符说明 ⚠️

Dashboard 通过 **图标 + 单元格背景** 两层方式呈现异常等级。

### 6.1 红色圈圈 🔴（最高优先级）

出现在 **Per-Instrument Detail expander 标题** 之前。

| 触发条件 | 含义 | 代码位置 |
|---------|------|---------|
| `risk_match == "red"` | 至少有一个合约的实际净仓位 ≠ 目标仓位（strategy 日志中的 risk_position） | `_check_risk_position_match()` |

> 红色 expander 整行的背景色为 `#ff4b4b`（红底白字）。

### 6.2 黄色圈圈 🟡（次优先级）

出现在 **expander 标题** 之前，或单元格背景。

#### 6.2.1 Expander 级别黄色 🟡

| 触发条件 | 含义 |
|---------|------|
| `has_warning == True` | 整个产品维度存在任一警告 |

`has_warning` 被置为 `True` 的所有路径：

| # | 触发位置 | 警告内容 |
|---|---------|---------|
| 1 | `account_info` 文件不存在 / 0 字节 | `File not found` |
| 2 | `account_info` 解析失败 | `account_info parsing error` |
| 3 | `position_data` 文件不存在 | `File not found` |
| 4 | **`position_data` 仅 header 无数据** | **🆕 清仓状态** → expander 标题附加 `(清仓)` |
| 5 | `trade_data` 缺失 | `File not found` |
| 6 | 合约无 static info | `no static info for {inst}` |
| 7 | 合约无价格 | `no price available for {inst}` |
| 8 | 单合约 margin_ratio 解析失败 | `margin_ratio error` |
| 9 | 单合约 risk_position 查询失败 | `risk_position error` |
| 10 | 单合约 trade_time 解析失败 | `trade_time error` |
| 11 | 单合约 uplimit 计算失败 | `uplimit calculation error` |
| 12 | 单合约 position 解析失败 | `position parsing error` |
| 13 | LONG / SHORT 行构造失败 | `LONG row error` / `SHORT row error` |
| 14 | trade_stats 汇总失败 | `trade stats calculation error` |
| 15 | MarketValue Ratio 失败 | `market value ratio calculation error` |
| 16 | bank 账户获取失败 | `bank account fetch error` |
| 17 | update_time 提取失败 | `update_time error` |
| 18 | `calculate_product` 整体抛异常 | `Calculation error: ...` |
| 19 | **🆕 `position_data` 为空** | `is_position_empty=True` 强制标记 |

#### 6.2.2 单元格级别黄色 🟡

`product_low_limit` 单元格：

| 条件 | 颜色 |
|------|------|
| `< 0.8` 且 product ≠ `ly1h` | 🔴 红色 `#ff4b4b` |
| `< 0.8` 且 product == `ly1h` | 🟡 **黄色 `#ffd700`**（ly1h 例外） |

> ⚠️ ly1h 的低水位阈值因为产品特性被特殊豁免，不视为告警。

### 6.3 单元格红色高亮 🔴

| 字段 | 触发条件 | 颜色 |
|------|---------|------|
| `max_margin` | `> 25%` | 红色 `#ff4b4b` |
| `product_low_limit` | `< 0.8`（ly1h 例外） | 红色 `#ff4b4b` |
| Detail 表整行 | `risk_match == "red"` | 红色 `#ff4b4b`（白字加粗） |

### 6.4 告警机制（WeChat Webhook）

仅在 **is_market_open == True** 时触发，避免非交易时段噪音：

| 告警条件 | 告警内容 |
|---------|---------|
| `product_low_limit < 0.8` 且 product ≠ `ly1h` | `[ALERT] product_low_limit < 0.8` |
| `max_margin > 0.25` | `[ALERT] max_margin > 0.25` |

通过 `send_alert()` 发送至企业微信机器人，失败静默。

### 6.5 异常等级优先级

```
🔴 红色圈圈   >  🟡 黄色圈圈   >  （无标记）
   (has_risk)      (has_warning)
```

只有当不存在任何红色风险时，才会显示黄色警告；两者皆无则不显示图标。

---

## 七、核心函数

### 7.1 数据加载

| 函数 | 职责 |
|------|------|
| `safe_read_csv(path)` | 安全读 CSV（捕获异常、0 字节、文件不存在） |
| `load_shared_files(market, path, current_date, market_open)` | 加载 static_info / 行情 / margin_uplimit，并更新价格缓存 |
| `load_risk_position(market, product, data_date)` | 从策略日志读取目标仓位 |
| `load_uplimit_holding_position()` | 从 CSV 读取持仓上限原始数据 |
| `init_price_cache(market, current_date)` | 用 `pre_settlement_price` 初始化价格缓存 |
| `update_price_cache(future_df)` | 用 ask/bid 中间价更新价格缓存 |
| `get_ch_client()` | ClickHouse 客户端（单例） |
| `get_product_clip(product_name)` | 查 product_clip 表 |
| `get_product_uplimit_coef(product_name)` | 查 uplimit_coef 表 |
| `rwp_api_login()` / `get_bank_account_balance(path)` | RWP 银行账户 |

### 7.2 计算核心

| 函数 | 职责 |
|------|------|
| `get_data_date(market, path, current_date, market_open)` | **核心日期逻辑**：盘前/盘后/夜盘次日 |
| `resolve_init_capital(cfg, pre_balance, balance)` | AUM 解析 |
| `_calc_trade_stats_product(trade_df, price_map, mul_map)` | 产品级 8 列汇总 |
| `_calc_trade_stats_for_inst(trade_df, inst, price, mul)` | 单合约 8 列 |
| `_check_risk_position_match(long, short, risk)` | 判断仓位是否匹配 |
| `_get_last_trade_time_adjusted(...)` | 提取最后成交时间（21:00 切日） |
| `calculate_product(...)` | **单产品完整计算入口** |

### 7.3 展示相关

| 函数 | 职责 |
|------|------|
| `dashboard()` | 主入口（Streamlit while 循环） |
| `display_overview_with_tooltips(styled_df)` | Overview + 字段说明 |
| `build_summary_table(df)` | 聚合 cncf / cnif / cn_all |
| `style_product_low_limit(row)` / `style_max_margin(val)` | Styler |

---

## 八、数据流概览

```
┌────────────────────────────────────────────────────┐
│  for each PRODUCT in PRODUCT_CONFIGS:              │
│                                                    │
│  1. get_data_date(market_open, current_date)        │
│     ├── 盘前 → 当前交易日                          │
│     ├── 盘后且有今日文件 → 今日                     │
│     ├── 盘后且无今日文件 → 前一交易日               │
│     └── 商品夜盘21:00后 → 次交易日                  │
│                                                    │
│  2. load_shared_files()                             │
│     ├── ins_static_info.csv → multiplier/exchange  │
│     ├── partial_market_data → update price_cache   │
│     └── margin_uplimit_{date}.csv → margin_ratio   │
│                                                    │
│  3. calculate_product()                             │
│     ├── account_info_{date}.csv → 资金字段          │
│     ├── position_data_{date}.csv → 持仓字段         │
│     │    └── (empty 时 → 标记清仓，has_warning=True)│
│     ├── trade_data_{date}.csv → 8列交易统计         │
│     ├── load_risk_position() → 目标仓位            │
│     ├── load_uplimit_holding_position() → 上限     │
│     └── RWP API → bank 余额                        │
│                                                    │
│  4. style + 格式化（%）→ DataFrame                  │
│  5. market_open 时触发 WeChat 告警                  │
└────────────────────────────────────────────────────┘
```

---

## 九、运行方式

```bash
# 1. 安装依赖
pip install streamlit pandas numpy requests clickhouse-connect

# 2. 准备 rwp_api（私有包）
#    需联系运维获取 rwp_api 模块

# 3. 启动
streamlit run dashboard.py
```

默认监听 `http://localhost:8501`。

---

## 十、配置清单（修改时常用）

| 场景 | 修改位置 |
|------|---------|
| 新增产品 | `PRODUCT_CONFIGS` 追加一条 |
| 新增路径银行账户 | `PRODUCT_BANK_MAPPING` 追加 |
| 修改 AUM 倍数 / 公式 | `PRODUCT_CONFIGS[i].aum_mul` 或 `aum_formula` |
| 修改告警阈值 | `dashboard()` 中 `pll < 0.8` / `imu > 0.25` |
| 修改告警通道 | `send_alert()` 中 webhook_url |
| 修改风险色 | `style_product_low_limit` / `style_max_margin` |
| 修改交易日历 | 替换 `/cpfs/intrastats/calendar` |

---

## 十一、已知限制 & 注意事项

1. **bank 字段**：fund_id ∈ {58, 215, 319, 34} 取硬编码常量，未对接 RWP 实时接口。
2. **持仓额 = 0 时**：原逻辑会跳过整个产品的 detail section；**新增补丁** 后，无论是否清仓都会渲染 expander（黄色圈圈 + `(清仓)` 后缀）。
3. **价格缺失兜底**：合约无价格时 price 取 0，相关市值 / 保证金 / 8 列统计全部为 0，并触发黄色警告。
4. **告警去重**：当前实现每次轮询都会触发一次告警，未做去重 / 节流，建议生产环境加滑动窗口或 Redis 去重。
5. **时区**：所有日期与时间均按服务器本地时区处理；夜盘 21:00 后会自动切到次日交易日。
6. **行情数据**：依赖 `partial_market_data_realtime/` 目录，盘中更新频率与上游相同（通常 1 秒级）。

---

## 十二、版本

- 文档版本：v1.0
- 配套代码版本：含 position-empty 补丁后的最终版

---

> 💡 **核心要点速记**：
> - 🔴 = `risk_match == red`（仓位与目标不符）
> - 🟡 = 任何 warning（包括清仓、文件缺失、合约无价、解析失败等）
> - 红色单元格 = `max_margin > 25%` 或 `product_low_limit < 0.8`（ly1h 例外）
> - 黄色单元格 = ly1h 的 `product_low_limit < 0.8`
