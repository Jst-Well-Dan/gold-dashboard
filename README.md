# 黄金研究看板（Gold Research Board）

不预测金价，只帮你看清**黄金正在反映什么**。

参照 [gold-board.betalpha.com](https://gold-board.betalpha.com/) 的「制度 → 宏观 → 市场」三层框架：
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

央行季度净购金（GDT 头条口径）**不需要手工维护**：`fetch_wgc_gdt` 全自动抓
（报告列表页找最新一期 slug → 报告的 central-banks 子页找图表 id → 取 Q1..Q4 × 年份矩阵），
按季度 30 天 TTL 更新，落 `data/raw/wgc/cb_gold_net_q.csv`。

- 走图表接口而不是 xlsx：`/download/file/*.xlsx` 对脚本返回 403 且要勾同意条款；
  `fsapi.gold.org/api/v12/charts/js/<slug>/<id>` 是公开的。
- **不用 WGC CBD 仪表盘的储备存量差分**：那只有 IMF 主动上报国（中位仅头条的 55%），
  而且差分会被回溯修订与报送滞后污染 —— 实测 2025Q2 算出 -236 吨（头条 +178），
  2026Q3 因为大量国家未报送直接崩到 -8,507 吨。存量差分 ≠ 净购金。
- 数据源是报告页内嵌的图表接口 `fsapi.gold.org/api/v12/charts/js/<slug>/<id>`，公开、无条款弹窗，
  **不需要浏览器**（`/download/file/...xlsx` 那个下载端点对脚本 403 且要勾同意条款，已放弃）。
- 脚本失败时不动已有 CSV，直接非零退出——日更读到旧数据继续出图，不会把图搞崩。

GPR 地缘政治威胁指数（`gpr:threat`）**同样不需要手工维护**：`fetch_gpr` 每月抓
`matteoiacoviello.com/gpr_files/data_gpr_export.xls`，取 `GPRT` 列（Threats 子项，类别 1–5），
覆盖 1985-01 起的 502 个月，落 `data/raw/gpr_threat_monthly.csv`。

- 官网只提供 BIFF8 格式的 `.xls`（2.7 MB，115 列），靠 `xlrd` 读 —— 所以 `requirements.txt` 里有它。
- 用 `month` + `GPRT` 两列，其余 113 列是国别子指数和替代口径，日更不用。
- 自动化后与原先手工导出的文件**逐字节一致**（503 行零差异），说明口径没有漂移。
- 每月初官网才更新，按 12 天 TTL 跑大概每月抓 2–3 次。

## 目录

```
scripts/
  config.py        指标注册表（42 条 → 41 个接口）、板块定义、图表清单 —— 加指标只改这里
  util.py          curl/requests 传输、CSV 读写、日志（含本机代理绕过）
  fetch.py         各数据源抓取 → data/raw/（抓不抓由 manifest 判定）
  manifest.py      抓取台账：TTL 分档、状态记录 → data/fetch_manifest.json
  compute.py       派生指标（同比/分位/回撤/财政压力/溢价…）→ data/board.json
  build_board.py   内联 CSS/JS/ECharts → docs/index.html
  build_status.py  台账 + 实际文件 → docs/status.html（每个接口的运行状态）
  run_daily.py     一键管线
web/
  template.html    页面骨架
  status_template.html  状态页骨架
  board.css        样式（暖白纸面 + 金箔头图）
  board.js         渲染层：板块图卡 + 历史洞察图（同一套 ECharts）
  vendor/echarts.min.js
.github/workflows/daily.yml   每交易日自动跑并发布到 Pages
data/
  raw/             原始序列（按源分目录，**不进仓库**，由 Actions 缓存承载）
  manual/          london_gold_daily.csv：伦敦现货金日频（Wind 一次导出后固化，1968–2026-03）
                   这是唯一固化的数据文件；其余全部每次自动抓取
  fetch_manifest.json  抓取台账（**不进仓库**，随 data/raw 一起走 Actions 缓存）
  board.json       前端消费的唯一数据文件（不进仓库，构建产物）
docs/index.html    单文件看板（构建产物，**不进仓库**，由 Actions 发布为 Pages artifact）
docs/status.html   数据状态页（构建产物，同上）
requirements.txt   运行依赖
```

管线四步，各自能单独跑：

| 步骤 | 命令 | 干什么 |
|---|---|---|
| 1 | `python scripts/fetch.py` | 按台账 TTL 抓数据源落盘 CSV，并写 `data/fetch_manifest.json` |
| 2 | `python scripts/compute.py` | 算派生量 + 卡片数据 + 图数据，并给每个板块排图序 |
| 3 | `python scripts/build_board.py` | 拼成单文件 HTML |
| 4 | `python scripts/build_status.py` | 台账 + 磁盘文件 → `docs/status.html` |
| 5 | `python scripts/run_daily.py` | 1→4 串起来（`--force` 无视 TTL，`--rebuild` 不联网） |

## 自动更新（GitHub Actions）

`.github/workflows/daily.yml` 每交易日跑一次：UTC 22:00（北京次日 06:00，此时美国前一交易日
的收盘数据已发布），也可在 Actions 页面手动触发，或勾选 `force` 全量重抓。

流程分两个 job：

1. **build**：抓数 → 计算 → 生成 `docs/` → 打包成 Pages artifact
2. **deploy**：把 artifact 发布到 GitHub Pages

**构建产物一律不进仓库**：`docs/`（1.6 MB 单文件）和 `data/fetch_manifest.json` 都在
`.gitignore` 里，前者直发 Pages artifact，后者与 `data/raw/` 一起放进 Actions 缓存。
这样每次运行**不产生任何提交**，也不会再出现两个运行同时改台账、`git push` 被拒的问题。
缓存丢了只是变慢（台账缺失时判定「本地无文件」，自动全量抓一次，约 2 分钟）。

**原始数据不进仓库**（`.gitignore` 里的 `data/raw/`），用 `actions/cache` 当跨运行的持久层。
缓存丢了不影响正确性：文件不存在时台账判定「本地无文件」，会自动全量抓一次，只是慢一点。

### 为什么不用文件时间判断缓存

GitHub Actions 每次都是全新 checkout，cache 恢复出来的文件 mtime 会被刷成「恢复那一刻」。
拿 `time.time() - st_mtime` 判断缓存，在 CI 里必然误判：要么全部当成新鲜永远不抓，要么全部
当成过期每天全量重抓。所以新鲜度只看 `data/fetch_manifest.json` 里记的时间戳，mtime 仅在
本地首次接入（还没有台账）时兜底。

### TTL 按发布频率分档

季/年度指标一年只变 1~4 次，没必要跟 VIX 一样每天重抓。过了 TTL 才发请求：

| 档位 | TTL | 覆盖哪些 |
|---|---|---|
| 日频 | 8 小时 | 实际利率、盈亏平衡、广义美元、汇率、GVZ、VIX、金价、股债 ETF、上金所、每日国债 |
| 周频 | 2 天 | NFCI、WALCL（H.4.1）、CFTC 持仓、比特币市值 |
| 月频 | 12 天 | CPI、核心 PCE、失业率、制造业产出、联邦基金利率 |
| 季频 | 30 天 | 债务/GDP、国债总规模、美元储备占比、央行季度净购金（WGC GDT） |
| 年频 | 300 天 | 赤字/GDP、联邦收入、付息支出、付息/收入、财政压力评分 |

WGC 三个接口的官网更新节奏本来就是周，单独覆盖成 7 天。一天里按这套 TTL 实际只发约
22 个请求（原本 34 个），省掉的主要是季/年度那几个大文件。

**注意一个陷阱**：「跳过」不能更新 `last_attempt`。否则每次运行都把时间戳刷新，TTL 永远
到不了，那个接口就再也不会被抓了。台账里 `last_attempt`（真正发请求的时间）与
`last_check`（每次运行都更新的检查时间）是分开的。

## 数据状态页

`docs/status.html` 是给人看的运行状况表：按数据源分组，每行一个接口，列出

- **状态**：成功（绿）/ 跳过（空心绿，TTL 内未抓）/ 降级（黄，抓失败沿用旧数据）/ 失败（红）/ 手工（灰）
- **最近抓取**：真正发请求的时间，附相对时间
- **数据截至**：磁盘上那份文件里最后一条数据的日期；超过该频率的合理滞后会标黄
  （例如债务/GDP 由 FRED 发布时本身就滞后两个季度，这里会如实暴露，不假装新鲜）
- **最新值 / 行数 / 备注**：值按单位格式化，备注写跳过原因或错误信息

顶部是本次运行的统计卡与一句话结论。数据日期与数值都是渲染时现读文件得到的，
不是抄台账，所以表格里的「数据」永远等于磁盘上的真实内容。

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

## 三层框架与口径

页面顺序（也是 tab 顺序）。三层从慢到快排列，贝塔阿尔法的因果链是「制度 → 宏观 → 市场 → 金价结果」；
金价走势是结果，历史洞察是背景参照：

| tab | 看什么 | 主要来源 |
|---|---|---|
| 01 金价走势 | 金价走势（对数，1971 年脱钩至今，全程日线）+ 人民币金价（2000-08 起日频，同一套时间轴上下叠放） | 1968–2026-03 伦敦市场现货金日频定盘价（`data/manual/london_gold_daily.csv`，Wind 一次性导出后固化）+ 2026-03-18 起 Yahoo `GC=F` 接续；人民币口径再乘汇率 |
| 02 历史洞察 | 长历史与参照图：上海金溢价、牛熊周期、回撤、年度涨跌、地缘威胁，以及金/BTC、金油比、黄金与大类资产的回报与相关性；配 verdict + 状态条 | 见各图注 |
| 03 制度层 | 债务/GDP、赤字/GDP、付息/收入、财政压力自建指数、美元储备占比、央行季度购金（变化最慢，季度/年度更新） | FRED + 财政部 debt-to-penny + IMF COFER + WGC |
| 04 宏观层 | 实际利率（10Y/5Y TIPS）、10Y 盈亏平衡通胀率；广义美元、NFCI 金融条件、美元兑人民币；核心 PCE、失业率、制造业产出、联储资产负债表 | FRED |
| 05 市场层 | GVZ 黄金波动率、VIX 股市波动率、CFTC 投机净多、金价 / 200 日均线偏离度（描述市场状态，不作为驱动因子） | FRED + CFTC Socrata + Yahoo |

**有意不纳入的维度**（本次三层重组时的决定，要加回来请先重新论证）：
- 信用利差：与金价的关系远，经由企业违约风险与流动性间接传导，不是干净的驱动因子。
- ETF 持仓与资金流：多数研究把它当作跟随价格的结果，驱动力弱；投机仓位已由 COT 覆盖。
- 首饰与工业需求、矿产供给：首饰需求随金价上升而下降，是价格的结果；年矿产供给约占地上存量 1.6%，边际影响小。
- 央行购金不在此列：它是政策性储备决策，归入制度层。

板块里的图来自两处（`config.py` 的 `SECTIONS[].charts` 决定归属）：

- 指标卡升级成的图：`SERIES` 里每条指标一张，图头摘要显示最新值、变化率与 10 年分位
- 从「历史洞察」并进板块的大图：`CHARTS` 里声明 id 即可，历史洞察里不再重复出现

`SECTIONS[].cards = "hide"` 表示该板块不渲染指标卡（目前只有「金价走势」用，它只要那两张长历史金价图）。
传一个 id 白名单则只渲染列表里的卡：`CPI_YOY`（只是宏观象限的输入）、`FYOINT`/`FYFR`（付息比的输入）、
`GOLD_MA`/`BTC_USD`/`BTC_MCAP` 都不出卡，但**数据照算**，仍会喂给派生指标和状态叙述。

同理以下指标也只算不用、默认不出卡（管线里照常抓取计算，改白名单即可放出）：`CPIAUCSL`、`GFDEBTN`/`US_DEBT_DAILY`、
`FEDFUNDS`/`SPY`/`QQQ`/`TLT`/`IEF`/`SHV`（利率与股债代理）、`SILVER`/`OIL`/`XAU`/`HUI`
（官方市场里的白银、原油与矿股指数，只出现在状态叙述里）、`GOLD_ANNUAL_CHANGE`/`GOLD_CNY`/`SHANGHAI_PREMIUM`
（官方市场派生，只在状态叙述与历史洞察里出现）。

**配色约定**：红涨绿跌（A 股 / 国内看板口径）——`--up` 与 `C.up` 是红 `#b8402f`、`--down` 与 `C.down` 是绿 `#2c7a54`。
因此「拉伸 / 均线上方」是红、「超跌 / 均线下方 / 回撤」是绿。改配色只改这两处 token，别在单张图里写死颜色。

**自建的三个量**（口径写在代码里，可改）：

- `FISCAL_STRESS` 财政压力指数 0-100 = 付息/收入(45%，>15% 后非线性放大) + 赤字/GDP(25%) + 债务/GDP(30%)
- `GOLD_CNY` = 美元金价 × 美元兑人民币 ÷ 31.1035（日频，起点是两者的公共起点 2000-08；人民币金价图与上海金溢价图都直接用它，不再降采样）
- `SHANGHAI_PREMIUM` = 上金所 Au99.99 ÷ 伦敦金折算价 − 1

## 数据源踩坑记录（重要）

1. **FRED 会拒浏览器 UA**：`fredgraph.csv` 走 Cloudflare，带 Chrome UA + 非浏览器 TLS 指纹会被判机器人（ReadTimeout / RemoteDisconnected）。所以 FRED 一律走系统 `curl` 且**不发 UA**（`util.curl_text`）。
2. **本机 Clash 代理会打断批量请求**：Windows 注册表里有 `127.0.0.1:7897`，Python `requests` 默认会走它，并发时 ProxyError。默认 `trust_env=False` 直连，需要走代理时设 `GOLD_USE_PROXY=1`。
3. **金价长历史用「固定现货 + 自动期货」拼接**：`GOLDAMGBD228NLBM` 在 FRED 已 404，LBMA 站点挡爬虫，Yahoo 的现货符号 `XAUUSD=X` 也已下架。所以采用：
   - **1968-01-02 ~ 2026-03-17**：伦敦市场现货金日频定盘价，Wind 一次性导出后固化在 `data/manual/london_gold_daily.csv`（14,405 个交易日，270 KB），不再抓取。
   - **2026-03-18 起**：Yahoo `GC=F`（COMEX 主力连续）自动接续。
   - 现货 vs 期货同日配对（6,237 个交易日）：价差中位 **+0.08%**、均值 +0.11%、95% 分位 +1.14%，只有 1.2% 的交易日超过 2%，所以接续处看不出台阶。
   - **导出时的两个清洗要点**：Wind 原始序列在 1985 年后给周末/节假日做了前值填充（周末值 100% 等于前一日），必须去掉「与前值完全相同」的行，否则 31% 的零收益会污染波动率与动量；2026-03-31 那条与 2026-03-11 数值完全相同、且与 COMEX 同日差 -10.3%，是脏数据，直接丢弃。
   - 这替代了原先基于 `datasets/gold-prices` 的**月度均价**序列。月均价会把月内极值抹平：2026-01 现货峰值 5405 被压成 5020，当前回撤 -24.2% 被压成 -18.2%，而 -20% 恰好是状态条的一个判定阈值，会直接把「偏利空」错判成「中性」。
4. **Yahoo `range=max` 会偷偷降采样成月线**：必须用 `period1=0&period2=...&interval=1d` 才拿到日频全历史。
5. **WGC 央行购金的三个口径，别混用**（2026-11 实测）：
   - GDT 头条（含未上报国估算）：`fetch_wgc_gdt` 自动抓（`fsapi.gold.org/api/v12/charts/js/*`）→ `data/raw/wgc/cb_gold_net_q.csv`。**图上一律用这个。**
   - WGC CBD 仪表盘（`fsapi.gold.org/api/cbd/...`，IMF 上报口径）：**已弃用并移除**。它只有主动上报国，而且拿储备存量做差分求净购金会被回溯修订和报送滞后污染（见上一节）。原先的「CSV 缺失时回退到 CBD」已删掉 ——回退出来的图会出负数，比没图更糟。
   - IMF `IMF.STA:IL` / `RGV_REVS`（fine troy oz，月度，`api.imf.org` SDMX 2.1，免费）：可自己按国加总，但要剔 `G001/G110/G200/GX010` 这些聚合码（`G001` 是全球合计 36971 吨），且同样是上报口径，同样不能当头条用。
   - GDT 报告的 `/download/file/...xlsx` 对脚本返回 **403**（Cloudflare），浏览器里下载还要先勾同意条款 —— 所以脚本绕开 xlsx，直接读报告页内嵌的图表接口 `fsapi.gold.org/api/v12/charts/js/<slug>/<id>`（公开、无弹窗）。
   - COFER 走 `api.imf.org` SDMX 正常。
6. **不同频率序列不能共用类目轴**：多序列图统一用 `type:'time'` 时间轴，否则按位置对齐会错位（日频的 BTC 与月频的金价差半个月就会错开刻度）。金价长历史图是月频接日频的同一条线，也必须走时间轴：类目轴每条观测等宽，会把 26 年日线拉成 95% 宽度、把前面 30 年压成一条竖线。

## 加一个指标

1. `scripts/config.py` → `SERIES` 里加一条（`id / name / section / src / unit / decimals / freq / gold / note`）
2. 若要新图表：`CHARTS` 里加一条 + `web/board.js` 的 `builders` 里加同名渲染函数
3. `python scripts/run_daily.py`

`freq` 决定图头摘要显示哪几种变化率：`d`=5日/20日/3月/同比，`w`=4周/13周/同比，`m`=环比/3月/同比，`q`/`a`=环比/同比。
`gold` 是「该指标上行对黄金偏多(bull)/偏空(bear)」的方向标签，只影响状态叙述。

## 部署

首次推到 GitHub 后，在仓库 **Settings → Pages → Source** 选 **GitHub Actions**（不是
"Deploy from a branch"），然后到 **Actions** 页面手动跑一次「更新看板」即可出站。
之后每个交易日 UTC 22:00 自动更新，站点地址形如 `https://<用户名>.github.io/<仓库名>/`。

本地预览不需要 Pages：

```bash
python scripts/run_daily.py --serve        # 生成后直接起本地服务
python -m http.server 8000 --directory docs  # 或者手动起
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
