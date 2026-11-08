# 黄金研究看板（Gold Research Board）

不预测金价，只帮你看清**黄金正在反映什么**。

参照 [gold-board.betalpha.com](https://gold-board.betalpha.com/) 的信息结构复刻：6 个观察维度、
30+ 张 ECharts 走势图（一个指标一张图，图头带最新值 + 涨跌 + 10 年分位）+ 5 张长历史金价图。
所有图的时间轴统一从 **1971 年 1 月**（美元与黄金脱钩）起。
**数据全部自己抓、自己算、自己存**，不依赖对方接口。

- 产出：`docs/index.html` —— 单文件、内嵌 ECharts、**双击即看**（file:// 也能用），可直接上 GitHub Pages
- 输入：`data/raw/` 下的原始 CSV（FRED / Yahoo / CFTC / 财政部 / IMF / Blockchain / WGC），可追溯、可重算
- 复现：`python scripts/run_daily.py`，一条命令跑完全程

```
国际金价 4,074.9 美元/盎司 · 年初至今 -5.88%
人民币金价 871.7 元/克 · 地上存量市值 28.8 万亿美元
```

## 一天怎么跑

```bash
python scripts/run_daily.py            # 抓数 → 计算 → 出页面（8 小时内有缓存就跳过抓取）
python scripts/run_daily.py --force    # 强制重抓全部数据
python scripts/run_daily.py --rebuild  # 只用已有 data/ 重建页面，不联网（改样式/图表时用）
python scripts/run_daily.py --serve    # 跑完起本地静态服务预览
```

Windows 直接双击 `run_daily.bat`，或双击根目录 `index.html`（跳转壳 → `docs/index.html`）。

## 目录

```
scripts/
  config.py        指标注册表（43 个）、板块定义、图表清单 —— 加指标只改这里
  util.py          curl/requests 传输、CSV 读写、日志（含本机代理绕过）
  fetch.py         各数据源抓取 → data/raw/
  compute.py       派生指标（同比/分位/回撤/财政压力/溢价…）→ data/board.json
  build_board.py   内联 CSS/JS/ECharts → docs/index.html
  run_daily.py     一键管线
web/
  template.html    页面骨架
  board.css        样式（暖白纸面 + 金箔头图）
  board.js         渲染层：板块图卡 + 历史洞察图（同一套 ECharts）
  vendor/echarts.min.js
data/
  raw/             原始序列（按源分目录）
  manual/          需要人工维护的年度序列（央行购金）
  board.json       前端消费的唯一数据文件
docs/index.html    单文件看板（构建产物）
```

管线四步，各自能单独跑：

| 步骤 | 命令 | 干什么 |
|---|---|---|
| 1 | `python scripts/fetch.py` | 抓 10 类数据源落盘 CSV |
| 2 | `python scripts/compute.py` | 算派生量 + 卡片数据 + 图数据，并给每个板块排图序 |
| 3 | `python scripts/build_board.py` | 拼成单文件 HTML |
| 4 | `python scripts/run_daily.py` | 1→3 串起来 |

## 交互说明

所有板块与「历史洞察」用的是同一张图卡、同一套交互：

| 操作 | 效果 |
|---|---|
| 悬停 | 十字准星 + 日期与数值 |
| 1/3/5/10 年 tab | 切时间窗口重画（金价长历史图），右侧给出该窗口的涨跌幅 |
| 右上角 ⤢ / Esc | 全屏放大 / 还原 |
| 拖拽 | 横向平移（不劫持页面滚动） |
| shift + 滚轮 | 缩放时间轴 |

图卡的 `hist` 是**构建期自适应降采样**的（最近 140 个观测保持原始密度，更早按步长抽样，≤420 点），
点位多的图用 `lttb` 抽样，单文件体积仍控制在 1.9 MB 左右。页面按帧分批初始化图表，首屏不必等 50 张图。

## 六个维度与口径

页面顺序（也是 tab 顺序）：

| tab | 看什么 | 主要来源 |
|---|---|---|
| 01 金价走势 | 国际金价走势（对数，1971 年脱钩至今） | datasets/gold-prices 月度伦敦金价 |
| 02 历史洞察 | 5 张长历史金价图：人民币金价、上海金价差、对数同比、回撤、年度涨跌 | 见各图注 |
| 03 机会成本 | 10Y TIPS 实际利率、10Y 盈亏平衡通胀率 + 大类资产回报 | FRED + Yahoo |
| 04 美元与流动性 | 广义美元指数、NFCI 金融条件、美元兑人民币 + 联储资产负债表 vs 金价 | FRED `DTWEXBGS` `NFCI` `DEXCHUS` |
| 05 通胀与增长 | CPI/PCE 及同比、失业率、制造业产出 + 金油比（金价/油价） | FRED `CPIAUCSL` `PCEPILFE` `UNRATE` `IPMAN` |
| 06 财政与信用 | 债务/GDP、赤字/GDP、付息/收入、财政压力自建指数、央行购金、美元储备占比、联储资产负债表 | FRED + 财政部 debt-to-penny + WGC + IMF COFER |
| 07 风险温度 | GVZ 隐含波动率、CFTC COT 头寸、金价 / 200 日均线偏离度 + 比特币的黄金计价（1 BTC 值多少盎司黄金） | FRED + Yahoo + CFTC Socrata |

板块里的图来自两处（`config.py` 的 `SECTIONS[].charts` 决定归属）：

- 指标卡升级成的图：`SERIES` 里每条指标一张，图头摘要显示最新值、变化率与 10 年分位
- 从「历史洞察」并进板块的大图：`CHARTS` 里声明 id 即可，历史洞察里不再重复出现

`SECTIONS[].cards = "hide"` 表示该板块不渲染指标卡（目前只有「金价走势」用，它只要那张长历史金价图）。
传一个 id 白名单则只渲染列表里的卡：`FYOINT`/`FYFR`（只是付息比的输入）、`GLD`/`GOLD_MA`/`BTC_USD`/`BTC_MCAP`
都不出图，但**数据照算**，仍会喂给派生指标和板块状态叙述。

同理以下指标也只算不用、默认不出图（管线里照常抓取计算，改白名单即可放出）：`DFII5`（机会成本）、
`FEDFUNDS`/`SPY`/`QQQ`/`TLT`/`IEF`/`SHV`（机会成本里的利率与股债代理）、`SILVER`/`OIL`/`XAU`/`HUI`
（官方市场里的白银、原油与矿股指数，只出现在状态叙述里）、`GOLD_ANNUAL_CHANGE`/`GOLD_CNY`/`SHANGHAI_PREMIUM`
（官方市场派生，只在状态叙述与历史洞察里出现）。

**配色约定**：红涨绿跌（A 股 / 国内看板口径）——`--up` 与 `C.up` 是红 `#b8402f`、`--down` 与 `C.down` 是绿 `#2c7a54`。
因此「拉伸 / 均线上方」是红、「超跌 / 均线下方 / 回撤」是绿。改配色只改这两处 token，别在单张图里写死颜色。

**自建的三个量**（口径写在代码里，可改）：

- `FISCAL_STRESS` 财政压力指数 0-100 = 付息/收入(45%，>15% 后非线性放大) + 赤字/GDP(25%) + 债务/GDP(30%)
- `GOLD_CNY` = 美元金价 × 美元兑人民币 ÷ 31.1035
- `SHANGHAI_PREMIUM` = 上金所 Au99.99 ÷ 伦敦金折算价 − 1

## 数据源踩坑记录（重要）

1. **FRED 会拒浏览器 UA**：`fredgraph.csv` 走 Cloudflare，带 Chrome UA + 非浏览器 TLS 指纹会被判机器人（ReadTimeout / RemoteDisconnected）。所以 FRED 一律走系统 `curl` 且**不发 UA**（`util.curl_text`）。
2. **本机 Clash 代理会打断批量请求**：Windows 注册表里有 `127.0.0.1:7897`，Python `requests` 默认会走它，并发时 ProxyError。默认 `trust_env=False` 直连，需要走代理时设 `GOLD_USE_PROXY=1`。
3. **LBMA 定盘价不再有公开 CSV**：`GOLDAMGBD228NLBM` 在 FRED 已 404，LBMA 站点也挡爬虫。日频改用 **COMEX 主力连续 `GC=F`**，长历史（1833 起）用 `datasets/gold-prices` 月度伦敦金价。
4. **Yahoo `range=max` 会偷偷降采样成月线**：必须用 `period1=0&period2=...&interval=1d` 才拿到日频全历史。
5. **WGC 与 IMF COFER 不好直连**：COFER 走 `api.imf.org` SDMX 正常；WGC 央行购金被挡，改为 `data/manual/cb_gold_net.csv` 每年手工追加一次（WGC Gold Demand Trends 年度数字）。
6. **不同频率序列不能共用类目轴**：多序列图统一用 `type:'time'` 时间轴，否则按位置对齐会错位（日频的 BTC 与月频的金价差半个月就会错开刻度）。

## 加一个指标

1. `scripts/config.py` → `SERIES` 里加一条（`id / name / section / src / unit / decimals / freq / gold / note`）
2. 若要新图表：`CHARTS` 里加一条 + `web/board.js` 的 `builders` 里加同名渲染函数
3. `python scripts/run_daily.py`

`freq` 决定图头摘要显示哪几种变化率：`d`=5日/20日/3月/同比，`w`=4周/13周/同比，`m`=环比/3月/同比，`q`/`a`=环比/同比。
`gold` 是「该指标上行对黄金偏多(bull)/偏空(bear)」的方向标签，只影响状态叙述。

## 部署

```bash
# GitHub Pages：把仓库推到远端，Pages 源目录选 /docs
# 或者本地：
python -m http.server 8000 --directory docs
```

单文件产物 `docs/index.html` 也可以直接发人（约 1.5 MB，含 ECharts，ECharts 授权 Apache-2.0）。

定时更新（Windows 任务计划，每个交易日 08:30 跑一次）：

```bat
schtasks /create /tn "黄金看板" /tr "E:\Python_Doc\Investment61107 黄金看板
un_daily.bat" /sc daily /st 08:30
```

## 还没做的

- 原站的「分析框架 · 四层拓扑图（21 节点）」独立页面（`/framework`），本仓库只做了仪表盘 + 历史洞察
- 登录/会员/头像等账号体系（自用不需要）
- 指标卡的手动排序与自选池

## 免责声明

看板只描述「发生了什么」，不提供买卖信号；仅供学习与研究参考，不构成投资建议。
