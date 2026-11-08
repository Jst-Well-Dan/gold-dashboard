"""看板配置：指标注册表、板块定义、图表清单。

约定：
- `gold` 极性表示「该指标上行对黄金是利多(bull)/利空(bear)/中性(neutral)」，
  只用于卡片标签与叙述，不影响数值。
- `scale` 是原始值到展示值的换算系数（例如 FRED 的百万美元 → 万亿美元 = 1e-6）。
- `freq` 决定卡片显示哪几种变化率，见 compute.change_windows。
"""

from __future__ import annotations

SECTIONS = [
    {
        "key": "officialmarket",
        "title": "金价走势",
        "subtitle": "1971 年美元与黄金脱钩以来的国际金价，对数坐标看长期趋势",
        "anchor": "gold-price",
        # charts = 从「历史洞察」并入本板块的大图；cards="hide" 表示不渲染指标卡
        "charts": ["gold_long_log"],
        "cards": "hide",
    },
    {
        "key": "opportunitycost",
        "title": "机会成本",
        "subtitle": "实际利率、名义利率与风险资产的相对吸引力",
        "anchor": "opportunity-cost",
        "charts": ["asset_returns"],
        "cards": ["DFII10", "T10YIE"],
    },
    {
        "key": "dollarliquidity",
        "title": "美元与流动性",
        "subtitle": "美元强弱、金融条件松紧，决定黄金的计价分母与流动性水位",
        "anchor": "dollar-liquidity",
        "charts": ["walcl_gold"],
    },
    {
        "key": "inflationgrowth",
        "title": "通胀与增长",
        "subtitle": "通胀决定购买力叙事，增长决定实际利率方向，二者合成宏观象限",
        "anchor": "inflation-growth",
        "charts": ["gold_oil_ratio"],
    },
    {
        "key": "fiscalcredit",
        "title": "财政与信用",
        "subtitle": "债务、赤字与付息压力是黄金最长期的结构性利多来源",
        "anchor": "fiscal-credit",
        # FYOINT / FYFR 只是 INTEREST_RATIO、FISCAL_STRESS 的输入，不再单独出图
        "cards": ["US_DEBT_DAILY", "GFDEBTN", "GFDEGDQ188S", "FYFSGDA188S",
                  "INTEREST_RATIO", "FISCAL_STRESS", "CB_GOLD_NET",
                  "USD_RESERVE_SHARE", "WALCL"],
    },
    {
        "key": "risktemperature",
        "title": "风险温度",
        "subtitle": "投机头寸、隐含波动率与替代资产，衡量市场是否过热或恐慌",
        "anchor": "risk-temperature",
        # GLD / GOLD_MA / BTC_USD / BTC_MCAP 不出指标卡（口径信息保留在板块状态叙述里），
        # 但 BTC_USD 会喂给 gold_vs_btc 比值图
        "cards": ["GVZCLS", "GOLD_COT"],
        "charts": ["gold_ma_gap", "gold_vs_btc"],
    },
]

# freq: d=日频, w=周频, m=月频, q=季频, a=年频
# delta: 该指标图头摘要的变化量口径。不填则按 unit 自动推导——
#        percent / cny_per_usd 用点差(diff)，其余用涨跌幅(pct)。
#        但零附近波动的序列（NFCI、净头寸）必须显式写 delta="diff"：
#        基数接近 0 时涨跌幅会爆炸（如 -0.01 → -0.02 算出 +100%），毫无意义。
SERIES = [
    # ---------------- 美元与流动性
    dict(id="DTWEXBGS", name="广义美元指数", section="dollarliquidity",
         src=("fred", "DTWEXBGS"), unit="index", decimals=2, freq="d", gold="bear",
         note="美联储广义贸易加权美元指数，覆盖 26 个贸易伙伴，比 DXY 更能反映真实竞争力。"),
    dict(id="NFCI", name="芝加哥联储金融条件指数", section="dollarliquidity",
         src=("fred", "NFCI"), unit="index", decimals=2, freq="w", gold="bear", delta="diff",
         note="综合货币市场、债券、股票与影子银行的 105 个指标；正值表示金融条件紧于平均。"),
    dict(id="DEXCHUS", name="美元兑人民币汇率", section="dollarliquidity",
         src=("fred", "DEXCHUS"), unit="cny_per_usd", decimals=3, freq="d", gold="bear",
         note="人民币金价的换算分母；汇率贬值时以人民币计价的黄金被动抬升。"),

    # ---------------- 通胀与增长
    dict(id="CPIAUCSL", name="CPI 物价指数", section="inflationgrowth",
         src=("fred", "CPIAUCSL"), unit="index", decimals=2, freq="m", gold="bull",
         note="美国城市消费者物价指数（季调），通胀的核心度量。"),
    dict(id="CPI_YOY", name="CPI 同比", section="inflationgrowth", derived=True,
         unit="percent", decimals=2, freq="m", gold="bull",
         note="CPI 同比增速，美联储 2% 目标的锚。"),
    dict(id="PCEPILFE", name="核心 PCE 物价指数", section="inflationgrowth",
         src=("fred", "PCEPILFE"), unit="index", decimals=2, freq="m", gold="bull",
         note="剔除食品能源的 PCE，美联储真正盯的通胀指标。"),
    dict(id="PCE_YOY", name="核心 PCE 同比", section="inflationgrowth", derived=True,
         unit="percent", decimals=2, freq="m", gold="bull",
         note="核心 PCE 同比，政策利率调整的主要依据。"),
    dict(id="UNRATE", name="美国失业率", section="inflationgrowth",
         src=("fred", "UNRATE"), unit="percent", decimals=1, freq="m", gold="bull",
         note="就业市场温度；失业率上行通常推动美联储转向宽松。"),
    dict(id="IPMAN", name="工业生产：制造业指数", section="inflationgrowth",
         src=("fred", "IPMAN"), unit="index", decimals=2, freq="m", gold="bear",
         note="制造业产出指数（2017=100），衡量实体经济增长动能。"),

    # ---------------- 财政与信用
    dict(id="GFDEBTN", name="美国国债总规模（季度）", section="fiscalcredit",
         src=("fred", "GFDEBTN"), scale=1e-6, unit="trillion_usd", decimals=2, freq="q",
         gold="bull", note="联邦政府未偿债务总额，季度口径。"),
    dict(id="US_DEBT_DAILY", name="美国国债总规模（日频）", section="fiscalcredit",
         src=("treasury", "debt_to_penny"), scale=1e-12, unit="trillion_usd", decimals=3,
         freq="d", gold="bull", note="财政部 Debt to the Penny 每日未偿债务。"),
    dict(id="GFDEGDQ188S", name="联邦债务 / GDP", section="fiscalcredit",
         src=("fred", "GFDEGDQ188S"), unit="percent", decimals=1, freq="q", gold="bull",
         note="债务占 GDP 比重，衡量债务可持续性。"),
    dict(id="FYFSGDA188S", name="财政赤字 / GDP", section="fiscalcredit",
         src=("fred", "FYFSGDA188S"), unit="percent", decimals=2, freq="a", gold="bull",
         note="联邦财政收支占 GDP 比例，负值即赤字。"),
    dict(id="FYOINT", name="联邦政府付息支出", section="fiscalcredit",
         src=("fred", "FYOINT"), scale=1e-6, unit="trillion_usd", decimals=3, freq="a",
         gold="bull", note="联邦政府净利息支出，滚动 12 个月口径。"),
    dict(id="FYFR", name="联邦政府财政收入", section="fiscalcredit",
         src=("fred", "FYFR"), scale=1e-6, unit="trillion_usd", decimals=3, freq="a",
         gold="bull", note="联邦政府总收入，付息比例的分母。"),
    dict(id="INTEREST_RATIO", name="付息支出 / 财政收入", section="fiscalcredit",
         derived=True, unit="percent", decimals=2, freq="a", gold="bull",
         note="每收 100 元税要拿多少去还利息，财政纪律的核心压力指标。"),
    dict(id="WALCL", name="美联储资产负债表", section="fiscalcredit",
         src=("fred", "WALCL"), scale=1e-6, unit="trillion_usd", decimals=3, freq="w",
         gold="bull", note="美联储总资产（周频），扩表即流动性投放。"),
    dict(id="CB_GOLD_NET", name="全球央行净购金", section="fiscalcredit",
         src=("manual", "cb_gold_net"), unit="tons", decimals=0, freq="a", gold="bull",
         note="世界黄金协会口径的央行年度净购金（吨）。"),
    dict(id="USD_RESERVE_SHARE", name="美元在全球外储中的占比", section="fiscalcredit",
         src=("imf", "cofer"), unit="percent", decimals=1, freq="q", gold="bull",
         note="IMF COFER 口径的美元已分配储备占比，去美元化的直接刻度。"),
    dict(id="FISCAL_STRESS", name="美国财政压力指数", section="fiscalcredit",
         derived=True, unit="index", decimals=1, freq="a", gold="bull",
         note="自建合成指数（0-100）：付息/收入、赤字/GDP、债务/GDP 加权，利息项带非线性放大。"),

    # ---------------- 机会成本
    dict(id="DFII10", name="10Y TIPS 实际收益率", section="opportunitycost",
         src=("fred", "DFII10"), unit="percent", decimals=2, freq="d", gold="bear",
         note="持有黄金最直接的机会成本。2022 年后相关性显著减弱。"),
    dict(id="DFII5", name="5Y TIPS 实际收益率", section="opportunitycost",
         src=("fred", "DFII5"), unit="percent", decimals=2, freq="d", gold="bear",
         note="中期资金真实回报；与 10Y 的利差反映长端通胀预期。"),
    dict(id="T10YIE", name="10 年盈亏平衡通胀率", section="opportunitycost",
         src=("fred", "T10YIE"), unit="percent", decimals=2, freq="d", gold="bull",
         note="市场隐含的未来 10 年平均通胀。"),
    dict(id="FEDFUNDS", name="联邦基金利率", section="opportunitycost",
         src=("fred", "FEDFUNDS"), unit="percent", decimals=2, freq="m", gold="bear",
         note="有效联邦基金利率（月均）。"),
    dict(id="SPY", name="标普 500 ETF", section="opportunitycost",
         src=("yahoo", "SPY"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="风险资产的基准，衡量持有黄金的替代收益（复权价，含分红再投资）。"),
    dict(id="QQQ", name="纳斯达克 100 ETF", section="opportunitycost",
         src=("yahoo", "QQQ"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="成长股代表，与实际利率高度负相关（复权价）。"),
    dict(id="TLT", name="20+ 年期美国国债 ETF", section="opportunitycost",
         src=("yahoo", "TLT"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="长端久期资产，与黄金同受实际利率驱动（复权价）。"),
    dict(id="IEF", name="7-10 年期美国国债 ETF", section="opportunitycost",
         src=("yahoo", "IEF"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="中久期国债，避险属性与黄金相近（复权价）。"),
    dict(id="SHV", name="短期美国国债 ETF", section="opportunitycost",
         src=("yahoo", "SHV"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="现金代理，利率高于通胀时持有黄金的机会成本真实为正（复权价，除息锯齿已消除）。"),

    # ---------------- 风险温度
    dict(id="GVZCLS", name="GVZ 黄金隐含波动率", section="risktemperature",
         src=("fred", "GVZCLS"), unit="percent", decimals=2, freq="d", gold="neutral",
         note="黄金 30 天隐含波动率，突破 25 需警惕短期剧烈波动。"),
    dict(id="GLD", name="黄金 ETF（GLD）", section="risktemperature",
         src=("yahoo", "GLD"), unit="usd_price", decimals=2, freq="d", gold="bull",
         note="全球最大黄金 ETF，西方机构配置意愿的代理（复权价）。"),
    dict(id="GOLD_COT", name="黄金交易商头寸（CFTC COT）", section="risktemperature",
         src=("cot", "GOLD_COT"), unit="contracts", decimals=0, freq="w", gold="neutral", delta="diff",
         note="管理基金(MM)净多 vs 掉期商净空，衡量投机拥挤度。"),
    dict(id="GOLD_MA", name="200 日均线（金价动量）", section="risktemperature",
         derived=True, unit="usd", decimals=2, freq="d", gold="bull",
         note="金价相对三条均线的排列状态，多头/空头排列即趋势信号。"),
    dict(id="BTC_USD", name="比特币价格", section="risktemperature",
         src=("yahoo", "BTC-USD"), unit="usd_price", decimals=0, freq="d", gold="neutral",
         note="替代性「价值存储」资产，风险偏好与流动性敏感度极高。"),
    dict(id="BTC_MCAP", name="比特币市值", section="risktemperature",
         src=("crypto", "btc_mcap"), scale=1e-12, unit="trillion_usd", decimals=2, freq="w",
         gold="neutral", note="Blockchain.com 口径的比特币总市值（周频采样），与黄金、美债同尺度比较。"),

    # ---------------- 官方市场
    dict(id="GOLD", name="黄金价格（COMEX 主力连续）", section="officialmarket",
         src=("yahoo", "GC=F"), unit="usd", decimals=1, freq="d", gold="bull",
         note="COMEX 黄金期货主力连续，美元/盎司。LBMA 定盘价已不再提供公开 CSV，"
              "长历史另用月度伦敦金价序列。"),
    dict(id="GOLD_CNY", name="人民币金价", section="officialmarket", derived=True,
         unit="cny_per_gram", decimals=1, freq="d", gold="bull",
         note="伦敦金按当日汇率折算：美元/盎司 × 汇率 ÷ 31.1035。"),
    dict(id="SHANGHAI_PREMIUM", name="上海金溢价", section="officialmarket", derived=True,
         unit="percent", decimals=2, freq="d", gold="bull",
         note="上金所 Au99.99 相对伦敦金折算价的溢价，反映国内实物需求强度。"),
    dict(id="SILVER", name="白银价格", section="officialmarket",
         src=("yahoo", "SI=F"), unit="usd", decimals=2, freq="d", gold="bull",
         note="兼具货币与工业属性，牛市后期常加速追赶黄金。"),
    dict(id="OIL", name="原油价格（WTI）", section="officialmarket",
         src=("yahoo", "CL=F"), unit="usd_bbl", decimals=2, freq="d", gold="bull",
         note="通胀预期的实物锚，与黄金长期正相关但阶段性脱钩。"),
    dict(id="XAU", name="费城金银指数（XAU）", section="officialmarket",
         src=("yahoo", "^XAU"), unit="index", decimals=2, freq="d", gold="bull",
         note="金矿股指数，对金价有杠杆效应但长期跑输金价。"),
    dict(id="HUI", name="金甲虫指数（HUI）", section="officialmarket",
         src=("yahoo", "^HUI"), unit="index", decimals=2, freq="d", gold="bull",
         note="未对冲金矿股指数，对金价弹性更大。"),
    dict(id="GOLD_ANNUAL_CHANGE", name="黄金年收益率", section="officialmarket",
         derived=True, unit="percent", decimals=2, freq="a", gold="bull",
         note="年末收盘价相对上一年的涨跌幅。"),
]

# 只作为计算输入、不单独出卡片的序列
EXTRA_FRED = ["CPIAUCNS"]

UNIT_LABELS = {
    "usd": "美元/盎司",
    "usd_price": "美元",
    "usd_bbl": "美元/桶",
    "cny_per_usd": "CNY/USD",
    "cny_per_gram": "元/克",
    "percent": "%",
    "index": "",
    "trillion_usd": "万亿美元",
    "billion_usd": "亿美元",
    "million_usd": "百万美元",
    "tons": "吨",
    "contracts": "手",
}

# 图表清单（顺序即页面顺序）。渲染逻辑在 web/board.js 里按 id 分发。
CHARTS = [
    dict(id="gold_long_log", title="国际金价走势（对数）",
         note="1971 年 8 月美元与黄金脱钩以来的伦敦金价，对数坐标让长期百分比变化可读：1980 与 2011 两次见顶、其后漫长的横盘都在同一条线上。"),
    dict(id="cny_gold", title="人民币金价走势（对数）",
         note="按当日汇率折算的元/克金价。与美元金价的差异，就是汇率贡献的那部分收益。"),
    dict(id="shanghai_premium", title="上海金 vs 伦敦金价差",
         note="上金所 Au99.99 相对伦敦金折算价的溢价百分比。正值说明国内买家愿意支付更高价格，反映实物需求强度。"),
    dict(id="gold_bullbear", title="黄金牛熊周期（±20%）",
         note="用 ±20% 折返法把 1971 年以来的金价切成一段段牛熊：每段都从 0% 重新起算，红色向上爬到本轮顶、绿色跌破 0 到本轮底。峰谷标注是「转折月份 · 持续月数 · 本段累计 · 年化」，点 ⤢ 放大可看完整标注。"),
    dict(id="gold_drawdown", title="金价距高点回撤统计",
         note="每个时点相对历史高点的回撤幅度。1980 年见顶后长达 20 年的熊市最深回撤超过 60%。绿色区域越深代表跌得越惨。"),
    dict(id="gold_annual", title="金价年度涨跌幅",
         note="每年末收盘价相对上一年的百分比变化。红色为上涨年份，灰色为下跌年份。"),
    dict(id="asset_returns", title="黄金 vs 大类资产回报",
         note="各时间窗口下黄金与标普 500、纳指、长债、中债、短债的年化回报对比，下划线为该窗口最佳。"),
    dict(id="gold_ma_gap", title="金价 / 200 日均线偏离度",
         note="金价 ÷ 200 日均线 − 1。零轴上方是长期趋势之上的多头区，下方是空头区。"
              "两条点线是近 10 年均值 ±1.5σ：上方那条标「拉伸」，下方那条标「超跌」，越过点线即趋势极端地带，均值回归风险上升。"),
    dict(id="gold_vs_btc", title="比特币的黄金计价（1 BTC = 多少盎司黄金）",
         note="把比特币换成黄金计价：1 枚比特币值多少盎司黄金。比值升 = 贬值对冲的钱更愿意买比特币，降 = 回到黄金。"
              "2021.11 加密见顶后的崩塌、2022.11 FTX 后的跳升、2024 年 ETF 带来的回落，是最近三次清晰的轮动。"
              "深色实线为均值，点线为 ±1.5 倍标准差（随窗口重算）。比值跨两个数量级，均值和标准差都在对数空间算"
              "（算术标准差会算出负的盎司数）——所以这是一条单边采用曲线，只能读「相对均值强/弱」，不能当均值回归的贵/便宜。"),
    dict(id="gold_oil_ratio", title="金油比（金价 / 油价）",
         note="一盎司黄金能换多少桶原油。比值走高 = 黄金相对原油强（避险与货币属性主导），"
              "走低 = 原油相对强（通胀传导主导）；比值的拐点常对应主导因子的切换。"),
    dict(id="gpr_threat", title="地缘政治风险（GPR 威胁指数）",
         note="Caldara-Iacoviello 按报纸提及地缘紧张的文章占比编制，1985-2019 均值=100。"
              "用威胁（Threats）子项：市场对威胁的反应通常大于已发生的行动。"
              "这是媒体覆盖度指数、不是严重程度指数；与金价的关系时有时无，只做归因背景、不做信号。"),
    dict(id="walcl_gold", title="美联储资产负债表 vs 金价",
         note="2008 年后每轮扩表都伴随金价上涨；2022 年缩表期间金价却创新高，因为央行购金对冲了流动性收缩。"),
]

# 央行净购金：WGC 年度口径（吨）。2026 年为年内已公布季度累计，脚本会优先读 data/manual/cb_gold_net.csv
CB_GOLD_NET_SEED = [
    (2010, 79), (2011, 481), (2012, 544), (2013, 409), (2014, 584),
    (2015, 580), (2016, 395), (2017, 379), (2018, 656), (2019, 605), (2020, 255),
    (2021, 450), (2022, 1082), (2023, 1037), (2024, 1045), (2025, 863),
]

# 地上黄金存量（吨），WGC 估算口径
ABOVE_GROUND_TONNES = 219891
TROY_OZ_PER_TONNE = 32150.7466
