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
        "charts": ["gold_long_log", "cny_gold"],
        "cards": "hide",
    },
    {
        "key": "institution",
        "title": "制度层",
        "subtitle": "债务、赤字与付息压力，以及央行与储备体系：变化最慢的结构性支撑，按季度、年度更新",
        "anchor": "institution",
        # 这里的「信用」指主权信用（财政可持续性），不是企业信用利差
        # FYOINT / FYFR 只是 INTEREST_RATIO、FISCAL_STRESS 的输入，不单独出图
        # 国债总规模（GFDEBTN / US_DEBT_DAILY）只保留取数与口径，不出图
        # 央行购金只看季度上报口径一张图
        "cards": ["GFDEGDQ188S", "FYFSGDA188S", "INTEREST_RATIO", "FISCAL_STRESS", "USD_RESERVE_SHARE"],
        "charts": ["cb_net_quarterly"],
    },
    {
        "key": "macro",
        "title": "宏观层",
        "subtitle": "实际利率与通胀预期决定持有黄金的代价，美元与金融条件决定计价环境；增长与通胀是背景",
        "anchor": "macro",
        # CPI 同比只作为宏观象限的输入，不出卡（核心 PCE 才是美联储的口径）
        # 联储资产负债表归为流动性
        "cards": ["DFII10", "DFII5", "T10YIE", "DTWEXBGS", "NFCI", "DEXCHUS",
                  "WALCL", "PCE_YOY", "UNRATE", "IPMAN"],
        # 相对价格类图（金油比、金/BTC、大类资产相关性）不在本层，落到「历史洞察」
        "charts": [],
    },
    {
        "key": "market",
        "title": "市场层",
        "subtitle": "波动率、趋势与投机仓位，回答「市场现在处于什么状态」，不作为驱动因子",
        "anchor": "market",
        # GOLD_MA 的口径在图里；BTC_* 不出卡，只为历史洞察的相对价格图提供数据
        "cards": ["GVZCLS", "VIXCLS", "GOLD_COT"],
        "charts": ["gold_ma_gap"],
    },
]

# freq: d=日频, w=周频, m=月频, q=季频, a=年频
# delta: 该指标图头摘要的变化量口径。不填则按 unit 自动推导——
#        percent / cny_per_usd 用点差(diff)，其余用涨跌幅(pct)。
#        但零附近波动的序列（NFCI、净头寸）必须显式写 delta="diff"：
#        基数接近 0 时涨跌幅会爆炸（如 -0.01 → -0.02 算出 +100%），毫无意义。
SERIES = [
    # ---------------- 宏观层 · 美元与流动性
    dict(id="DTWEXBGS", name="广义美元指数", section="macro",
         src=("fred", "DTWEXBGS"), unit="index", decimals=2, freq="d", gold="bear",
         note="美联储广义贸易加权美元指数，覆盖 26 个贸易伙伴，比 DXY 更能反映真实竞争力。"),
    dict(id="NFCI", name="芝加哥联储金融条件指数", section="macro",
         src=("fred", "NFCI"), unit="index", decimals=2, freq="w", gold="bear", delta="diff",
         note="综合货币市场、债券、股票与影子银行的 105 个指标；正值表示金融条件紧于平均。"),
    dict(id="DEXCHUS", name="美元兑人民币汇率", section="macro",
         src=("fred", "DEXCHUS"), unit="cny_per_usd", decimals=3, freq="d", gold="bear",
         note="人民币金价的换算分母；汇率贬值时以人民币计价的黄金被动抬升。"),

    # ---------------- 宏观层 · 通胀与增长
    dict(id="CPIAUCSL", name="CPI 物价指数", section="macro",
         src=("fred", "CPIAUCSL"), unit="index", decimals=2, freq="m", gold="bull",
         note="美国城市消费者物价指数（季调），通胀的核心度量。"),
    dict(id="CPI_YOY", name="CPI 同比", section="macro", derived=True,
         unit="percent", decimals=2, freq="m", gold="bull",
         note="CPI 同比增速，美联储 2% 目标的锚。"),
    dict(id="PCEPILFE", name="核心 PCE 物价指数", section="macro",
         src=("fred", "PCEPILFE"), unit="index", decimals=2, freq="m", gold="bull",
         note="剔除食品能源的 PCE，美联储真正盯的通胀指标。"),
    dict(id="PCE_YOY", name="核心 PCE 同比", section="macro", derived=True,
         unit="percent", decimals=2, freq="m", gold="bull",
         note="核心 PCE 同比，政策利率调整的主要依据。"),
    dict(id="UNRATE", name="美国失业率", section="macro",
         src=("fred", "UNRATE"), unit="percent", decimals=1, freq="m", gold="bull",
         note="就业市场温度；失业率上行通常推动美联储转向宽松。"),
    dict(id="IPMAN", name="工业生产：制造业指数", section="macro",
         src=("fred", "IPMAN"), unit="index", decimals=2, freq="m", gold="bear",
         note="制造业产出指数（2017=100），衡量实体经济增长动能。"),

    # ---------------- 制度层 · 财政与储备
    dict(id="GFDEBTN", name="美国国债总规模（季度）", section="institution",
         src=("fred", "GFDEBTN"), scale=1e-6, unit="trillion_usd", decimals=2, freq="q",
         gold="bull", note="联邦政府未偿债务总额，季度口径。"),
    dict(id="US_DEBT_DAILY", name="美国国债总规模（日频）", section="institution",
         src=("treasury", "debt_to_penny"), scale=1e-12, unit="trillion_usd", decimals=3,
         freq="d", gold="bull", note="财政部 Debt to the Penny 每日未偿债务。"),
    dict(id="GFDEGDQ188S", name="联邦债务 / GDP", section="institution",
         src=("fred", "GFDEGDQ188S"), unit="percent", decimals=1, freq="q", gold="bull",
         note="债务占 GDP 比重，衡量债务可持续性。"),
    dict(id="FYFSGDA188S", name="财政赤字 / GDP", section="institution",
         src=("fred", "FYFSGDA188S"), unit="percent", decimals=2, freq="a", gold="bull",
         note="联邦财政收支占 GDP 比例，负值即赤字。"),
    dict(id="FYOINT", name="联邦政府付息支出", section="institution",
         src=("fred", "FYOINT"), scale=1e-6, unit="trillion_usd", decimals=3, freq="a",
         gold="bull", note="联邦政府净利息支出，滚动 12 个月口径。"),
    dict(id="FYFR", name="联邦政府财政收入", section="institution",
         src=("fred", "FYFR"), scale=1e-6, unit="trillion_usd", decimals=3, freq="a",
         gold="bull", note="联邦政府总收入，付息比例的分母。"),
    dict(id="INTEREST_RATIO", name="付息支出 / 财政收入", section="institution",
         derived=True, unit="percent", decimals=2, freq="a", gold="bull",
         note="每收 100 元税要拿多少去还利息，财政纪律的核心压力指标。"),
    dict(id="WALCL", name="美联储资产负债表", section="macro",
         src=("fred", "WALCL"), scale=1e-6, unit="trillion_usd", decimals=3, freq="w",
         gold="bull", note="美联储总资产（周频），扩表即流动性投放。"),
    dict(id="USD_RESERVE_SHARE", name="美元在全球外储中的占比", section="institution",
         src=("imf", "cofer"), unit="percent", decimals=1, freq="q", gold="bull",
         note="IMF COFER 口径的美元已分配储备占比，去美元化的直接刻度。"),
    dict(id="FISCAL_STRESS", name="美国财政压力指数", section="institution",
         derived=True, unit="index", decimals=1, freq="a", gold="bull",
         note="自建合成指数（0-100）：付息/收入、赤字/GDP、债务/GDP 加权，利息项带非线性放大。"),

    # ---------------- 宏观层 · 机会成本
    dict(id="DFII10", name="10Y TIPS 实际收益率", section="macro",
         src=("fred", "DFII10"), unit="percent", decimals=2, freq="d", gold="bear",
         note="持有黄金最直接的机会成本。2022 年后相关性显著减弱。"),
    dict(id="DFII5", name="5Y TIPS 实际收益率", section="macro",
         src=("fred", "DFII5"), unit="percent", decimals=2, freq="d", gold="bear",
         note="中期资金真实回报；与 10Y 的利差反映长端通胀预期。"),
    dict(id="T10YIE", name="10 年盈亏平衡通胀率", section="macro",
         src=("fred", "T10YIE"), unit="percent", decimals=2, freq="d", gold="bull",
         note="市场隐含的未来 10 年平均通胀。"),
    dict(id="FEDFUNDS", name="联邦基金利率", section="macro",
         src=("fred", "FEDFUNDS"), unit="percent", decimals=2, freq="m", gold="bear",
         note="有效联邦基金利率（月均）。"),
    dict(id="SPY", name="标普 500 ETF", section="macro",
         src=("yahoo", "SPY"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="风险资产的基准，衡量持有黄金的替代收益（复权价，含分红再投资）。"),
    dict(id="QQQ", name="纳斯达克 100 ETF", section="macro",
         src=("yahoo", "QQQ"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="成长股代表，与实际利率高度负相关（复权价）。"),
    dict(id="TLT", name="20+ 年期美国国债 ETF", section="macro",
         src=("yahoo", "TLT"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="长端久期资产，与黄金同受实际利率驱动（复权价）。"),
    dict(id="IEF", name="7-10 年期美国国债 ETF", section="macro",
         src=("yahoo", "IEF"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="中久期国债，避险属性与黄金相近（复权价）。"),
    dict(id="SHV", name="短期美国国债 ETF", section="macro",
         src=("yahoo", "SHV"), unit="usd_price", decimals=2, freq="d", gold="bear",
         note="现金代理，利率高于通胀时持有黄金的机会成本真实为正（复权价，除息锯齿已消除）。"),

    # ---------------- 市场层
    dict(id="GVZCLS", name="GVZ 黄金隐含波动率", section="market",
         src=("fred", "GVZCLS"), unit="percent", decimals=2, freq="d", gold="neutral",
         note="黄金 30 天隐含波动率，突破 25 需警惕短期剧烈波动。"),
    dict(id="VIXCLS", name="VIX 标普 500 隐含波动率", section="market",
         src=("fred", "VIXCLS"), unit="percent", decimals=2, freq="d", gold="neutral", delta="diff",
         note="标普 500 的 30 天隐含波动率，衡量股市恐慌。金价对它的方向不稳定：2008 年 10 月、"
              "2020 年 3 月恐慌时金价同跌，所以它只描述市场压力环境，不当作金价方向的信号。与 GVZ 同属波动率，一并看。"),
    dict(id="GOLD_COT", name="黄金交易商头寸（CFTC COT）", section="market",
         src=("cot", "GOLD_COT"), unit="contracts", decimals=0, freq="w", gold="neutral", delta="diff",
         note="管理基金(MM)净多 vs 掉期商净空，衡量投机拥挤度。"),
    dict(id="GOLD_MA", name="200 日均线（金价动量）", section="market",
         derived=True, unit="usd", decimals=2, freq="d", gold="bull",
         note="金价相对三条均线的排列状态，多头/空头排列即趋势信号。"),
    dict(id="BTC_USD", name="比特币价格", section="market",
         src=("yahoo", "BTC-USD"), unit="usd_price", decimals=0, freq="d", gold="neutral",
         note="替代性「价值存储」资产，风险偏好与流动性敏感度极高。"),
    dict(id="BTC_MCAP", name="比特币市值", section="market",
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
    dict(id="gold_long_log", title="金价走势（对数）",
         note="1971 年 8 月美元与黄金脱钩以来的国际金价，对数坐标让长期百分比变化可读："
              "1980 与 2011 两次见顶、其后漫长的横盘都在同一条线上。"
              "1971 年起是伦敦市场现货金日频定盘价，2026 年 3 月后由 COMEX 期货接续。"),
    dict(id="cny_gold", title="人民币金价走势（对数）",
         note="按当日汇率折算的元/克日频金价（美元金价 × 当日汇率 ÷ 31.1035），起点是美元金价与汇率都齐的 2000 年 8 月。"
              "与美元金价的差，就是汇率贡献的那部分收益。"),
    dict(id="shanghai_premium", title="上海金 vs 伦敦金价差",
         note="上金所 Au99.99 相对伦敦金折算价的溢价百分比。正值说明国内买家愿意支付更高价格，反映实物需求强度。"),
    dict(id="gold_bullbear", title="黄金牛熊周期（±20%）",
         note="用 ±20% 折返法把 1971 年以来的金价切成一段段牛熊：每段都从 0% 重新起算，红色向上爬到本轮顶、绿色跌破 0 到本轮底。峰谷标注是「转折月份 · 持续月数 · 本段累计 · 年化」，点 ⤢ 放大可看完整标注。"),
    dict(id="gold_drawdown", title="金价距高点回撤统计",
         note="每个时点相对历史高点的回撤幅度。1980 年见顶后长达 20 年的熊市最深回撤超过 60%。绿色区域越深代表跌得越惨。"),
    dict(id="gold_annual", title="金价年度涨跌幅",
         note="每年末收盘价相对上一年的百分比变化。红色为上涨年份，灰色为下跌年份。"),
    dict(id="cb_net_quarterly", title="全球央行净购金（季度）",
         note="WGC《Gold Demand Trends》季度报告的央行净购金（吨）。"),
    dict(id="gold_correlation", title="黄金与其他资产的相关性（WGC 官方口径）",
         note="WGC gold-returns 的 CNY 口径：7 个默认资产周收益率相关系数（近 6 年窗口）。"
              "范围 -1~+1，越接近 0 说明黄金与该资产越不同步、分散效果越好；对角线恒为 1。"),
    dict(id="asset_returns", title="黄金 vs 大类资产回报（WGC 官方口径）",
         note="世界黄金协会 gold-returns 的 CNY 口径：Au9999、现金、彭博中国政企债、MSCI 中美及新兴股市。"
              "年初至今为区间累计回报，10/20 年为复合年均（CAGR）。"),
    dict(id="gold_ma_gap", title="金价 / 200 日均线偏离度",
         note="金价 ÷ 200 日均线 − 1。零轴上方是长期趋势之上的多头区，下方是空头区。"
              "两条点线是近 10 年均值 ±1.5σ：上方那条标「拉伸」，下方那条标「超跌」，越过点线即趋势极端地带，均值回归风险上升。"),
    dict(id="gold_vs_btc", title="比特币的黄金计价（1 BTC = 多少盎司黄金）",
         note="把比特币换成黄金计价：1 枚比特币值多少盎司黄金。比值升 = 资金更愿意买比特币，"
              "降 = 回到黄金。点线为均值 ±1.5σ。"),
    dict(id="gold_oil_ratio", title="金油比（金价 / 油价）",
         note="一盎司黄金能换多少桶原油。比值走高 = 黄金相对原油强（避险与货币属性主导），"
              "走低 = 原油相对强（通胀传导主导）；比值的拐点常对应主导因子的切换。"),
    dict(id="gpr_threat", title="地缘政治风险（GPR 威胁指数）",
         note="Caldara-Iacoviello 按报纸提及地缘紧张的文章占比编制，1985-2019 均值=100。"
              "用威胁（Threats）子项：市场对威胁的反应通常大于已发生的行动。"
              "这是媒体覆盖度指数、不是严重程度指数；与金价的关系时有时无，只做归因背景、不做信号。"),
]

# 地上黄金存量（吨），WGC 估算口径
ABOVE_GROUND_TONNES = 219891
TROY_OZ_PER_TONNE = 32150.7466
