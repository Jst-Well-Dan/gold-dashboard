/* ==========================================================================
   黄金研究看板 · 渲染层
   输入：window.__BOARD__（build_board.py 注入的 payload）
   输出：头图 / 三层板块图卡 / 历史洞察长历史图（全部 ECharts）
   ========================================================================== */
(function () {
  'use strict';

  const B = window.__BOARD__;
  if (!B) return;

  const C = {
    gold: '#b8942e',
    goldBright: '#d4a853',
    goldSoft: '#e9d7a6',
    ink: '#1f1a12',
    ink2: '#4b4437',
    muted: '#8a8375',
    line: '#e6ddc9',
    /* 红涨绿跌：up = 红（上涨/利多），down = 绿（下跌/利空） */
    up: '#b8402f',
    down: '#2c7a54',
    blue: '#43689b',
    teal: '#2f6f6a',
    slate: '#8b8fa3',
  };

  const FONT = 'Inter, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';

  /* ------------------------------------------------------------ 小工具 */
  const fmtNum = (v, nd) => {
    if (v === null || v === undefined || !isFinite(v)) return '—';
    const abs = Math.abs(v);
    const digits = nd !== undefined ? nd : (abs >= 1000 ? 0 : abs >= 1 ? 2 : 3);
    return v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  };

  const signed = (v, suffix, nd) => (v > 0 ? '+' : v < 0 ? '' : '') + fmtNum(v, nd === undefined ? 2 : nd) + (suffix || '');

  /* 手/吨这类大整数单位的变化量不带小数；其余保留 2 位 */
  const deltaDigits = (c) => (c && (c.unit_key === 'contracts' || c.unit_key === 'tons') ? 0 : 2);

  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html !== undefined) n.innerHTML = html;
    return n;
  };

  /* 后缀跟着数据走（compute.delta_meta）：pct→%，diff→pp/点/手/…；
     老的 board.json 没有 delta_suffix 才回退到按 unit 猜 */
  const deltaSuffix = (c) => {
    if (c.delta_suffix !== undefined) return c.delta_suffix;
    const k = c.unit_key;
    return k === 'percent' ? 'pp' : k === 'cny_per_usd' ? '' : '%';
  };

  /* Hero 迷你走势线：构建期已抽稀到 ~120 点，前端只按 viewBox 拉伸画线。
     深色底上用金色中性线（不暗示多空），末端圆点标最新价。 */
  function sparkSVG(pts) {
    if (!pts || pts.length < 2) return '';
    const W = 220, H = 56, P = 3;
    const vs = pts.map((p) => p[1]);
    const lo = Math.min(...vs), hi = Math.max(...vs);
    const X = (i) => P + (i * (W - 2 * P)) / (pts.length - 1);
    const Y = (v) => (hi === lo ? H / 2 : H - P - ((v - lo) * (H - 2 * P)) / (hi - lo));
    const line = pts.map((p, i) => `${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ');
    const lx = X(pts.length - 1).toFixed(1), ly = Y(vs[vs.length - 1]).toFixed(1);
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">` +
      `<title>近一年走势（${pts[0][0]} → ${pts[pts.length - 1][0]}）</title>` +
      `<polygon points="${P},${H} ${line} ${W - P},${H}" fill="rgba(212,168,83,.16)"/>` +
      `<polyline points="${line}" fill="none" stroke="#d4a853" stroke-width="1.5"/>` +
      `<circle cx="${lx}" cy="${ly}" r="2.6" fill="#f0dfb4"/></svg>`;
  }

  /* ------------------------------------------------------------- 降级横幅 */
  /* 抓取失败/沿用旧缓存的接口在页顶汇总。只有 WGC 两张图会在图内自带警告，
     其余接口如果不在汇总横幅，页面上就完全看不出「这是几天前的数」。 */
  function renderAlerts() {
    const root = document.getElementById('alert-bar');
    if (!root) return;
    const list = (B.alerts || []).filter((a) => a && a.status);
    if (!list.length) { root.innerHTML = ''; return; }
    const fails = list.filter((a) => a.status === 'fail');
    const stales = list.filter((a) => a.status === 'stale');
    const names = (arr) => arr.slice(0, 4).map((a) => a.label).join('、')
      + (arr.length > 4 ? ` 等 ${arr.length} 项` : '');
    const parts = [];
    if (fails.length) parts.push(`<strong>${names(fails)}</strong> 本次抓取失败，相关图表已留空`);
    if (stales.length) parts.push(`<strong>${names(stales)}</strong> 沿用上次数据，不是最新值`);
    root.innerHTML = `<div class="alert-bar">
        <span class="alert-icon">⚠</span>
        <span class="alert-text">${parts.join('；')}</span>
        <a class="alert-link" href="status.html">查看抓取状态 →</a>
      </div>`;
  }

  /* --------------------------------------------------------------- 头图 */
  function renderHero() {
    const root = document.getElementById('hero-stats');
    if (!root || !B.hero) return;
    const h = B.hero;
    const cards = [];

    if (h.gold) {
      const g = h.gold;
      cards.push(`
        <div class="hero-stat">
          <div class="label"><span>国际金价 · COMEX</span>
            <span class="pill ${g.chg_1d > 0 ? 'up' : g.chg_1d < 0 ? 'down' : 'flat'}">${signed(g.chg_1d, '%')}</span>
          </div>
          <div class="big num">${fmtNum(g.value, 1)}<small>美元/盎司</small></div>
          ${sparkSVG(g.spark)}
          <div class="meta">年初至今 ${signed(g.chg_ytd, '%')} · 近一年 ${signed(g.chg_1y, '%')} · ${g.date}</div>
        </div>`);
    }
    if (h.gold_cny) {
      const c = h.gold_cny;
      cards.push(`
        <div class="hero-stat">
          <div class="label"><span>人民币金价 · 上金所</span>
            <span class="pill ${c.chg_1d > 0 ? 'up' : c.chg_1d < 0 ? 'down' : 'flat'}">${signed(c.chg_1d, '%')}</span>
          </div>
          <div class="big num">${fmtNum(c.value, 1)}<small>元/克</small></div>
          <div class="meta">上金所 Au99.99 成交价 · ${c.date}</div>
        </div>`);
    }
    if (h.drivers && h.drivers.length) {
      const tones = { good: '#ff9b8c', bad: '#8fdcae', warn: '#f0d48a', neutral: 'rgba(255,255,255,.78)' };
      const rows = h.drivers
        .map((dr) => `<a class="driver-row" href="${dr.anchor}"><span>${dr.label}</span>` +
          `<b style="color:${tones[dr.tone] || tones.neutral}">${dr.value}` +
          `${dr.date ? `<i>· ${dr.date.slice(5)}</i>` : ''}</b></a>`)
        .join('');
      /* 多空拉扯一句话：偏多的 vs 偏空的，纯由 tone 推导 */
      const bull = h.drivers.filter((dr) => dr.tone === 'good').map((dr) => dr.label);
      const bear = h.drivers.filter((dr) => dr.tone === 'bad').map((dr) => dr.label);
      const tension = bull.length && bear.length
        ? `${bull.join('、')}偏多 vs ${bear.join('、')}偏空`
        : bull.length ? `${bull.join('、')}偏多，暂无明显逆风`
        : bear.length ? `${bear.join('、')}偏空，顺风暂缺`
        : '多空暂处均势';
      cards.push(`
        <div class="hero-stat">
          <div class="label"><span>核心驱动</span><span class="pill flat">三变量</span></div>
          <div class="driver-rows">${rows}</div>
          <div class="meta">${tension}</div>
        </div>`);
    }
    if (h.outlook && h.outlook.items && h.outlook.items.length) {
      const pillCls = { good: 'up', bad: 'down', warn: 'warn', neutral: 'flat' };
      const pills = h.outlook.items
        .map((it) => `<a class="pill ${pillCls[it.tone] || 'flat'}" href="#${it.anchor}">${it.title} · ${it.verdict}</a>`)
        .join('');
      cards.push(`
        <div class="hero-outlook">
          <div class="sum">综合：${h.outlook.summary}</div>
          <div class="pills">${pills}</div>
        </div>`);
    }
    root.innerHTML = cards.join('');
  }

  /* 价格为正时可切对数轴 */
  const LOGGABLE = new Set(['usd', 'usd_price', 'usd_bbl', 'index', 'trillion_usd',
    'billion_usd', 'million_usd', 'contracts', 'tons', 'cny_per_gram']);

  /* --------------------------------------------------------------- 导航 */
  /* tab 顺序：金价走势 → 历史洞察 → 其余板块；编号与板块标题共用同一套 */
  function navItems() {
    const items = [];
    const secs = B.sections || [];
    if (secs[0]) items.push({ type: 'section', sec: secs[0], anchor: secs[0].anchor, title: secs[0].title });
    items.push({ type: 'insights', anchor: 'insights', title: '历史洞察' });
    secs.slice(1).forEach((sec) => items.push({ type: 'section', sec, anchor: sec.anchor, title: sec.title }));
    items.forEach((it, i) => { it.no = String(i + 1).padStart(2, '0'); });
    return items;
  }

  let ITEMS = [];

  function renderNav() {
    const nav = document.getElementById('nav-links');
    if (!nav) return;
    ITEMS = navItems();
    nav.innerHTML = ITEMS
      .map((it) => `<a href="#${it.anchor}">${it.no} ${it.title}</a>`)
      .join('');
    const stamp = document.getElementById('nav-stamp');
    if (stamp) {
      /* 生成时间 + 金价截至日：宏观指标滞后较多，各条的截至日见状态条右上角 */
      const gd = (B.hero && B.hero.gold && B.hero.gold.date) || '';
      stamp.textContent = '更新 ' + B.generated_at_local + (gd ? ` · 金价截至 ${gd.slice(5)}` : '');
    }
  }

  /* ------------------------------------------------- 图卡（两种来源） */
  /* 板块里的图有两种：
       kind='card'    指标卡升级成的图，直接用 card.hist 画线
       kind='insight' 历史洞察的大图，用 B.charts + builders 画
     两者共用同一套 .chart-card 外观与交互，和「历史洞察」完全一致。 */
  const cardById = new Map();
  (B.sections || []).forEach((s) => (s.cards || []).forEach((c) => cardById.set(c.id, c)));

  function chartCardHTML(entry) {
    const isCard = entry.kind === 'card';
    const d = isCard ? cardById.get(entry.id) : B.charts[entry.id];
    if (!d) return '';
    const cls = ['chart-card', !isCard && WIDE.has(entry.id) ? 'wide' : ''].join(' ').trim();
    const extra = isCard
      ? cardStatsHTML(d)
      : [(d.warn ? `<div class="warn">${d.warn}</div>` : ''),
         (d.extra ? `<div class="extra">${d.extra}</div>` : '')].join('');
    const tabs = hasRangeTabs(entry.id) ? rangeTabsHTML(entry.id) : '';
    return `<article class="${cls}" id="chart-${entry.id}">
          <button class="chart-expand" type="button" data-expand="${entry.id}" aria-label="放大图表">⤢</button>
          <h3>${isCard ? d.name : d.title}</h3>
          <p class="note">${d.note || ''}</p>
          ${extra}
          ${tabs}
          <div class="chart-canvas" data-chart="${entry.id}"></div>
        </article>`;
  }

  /* 时间窗口 tab：切窗口后重画，并把这个窗口的涨跌幅写在右边 */
  function rangeTabsHTML(id) {
    return `<div class="chart-tabs" data-tabs="${id}">${RANGES
      .map(([label, years]) =>
        `<button type="button" data-years="${years === null ? '' : years}"${years === null ? ' class="on"' : ''}>${label}</button>`)
      .join('')}<span class="tab-delta"></span></div>`;
  }

  /* 窗口内实时算中位数 */
  function medianOf(values) {
    const vs = (values || []).filter((v) => typeof v === 'number' && !Number.isNaN(v)).sort((a, b) => a - b);
    if (!vs.length) return null;
    const m = vs.length >> 1;
    return vs.length % 2 ? vs[m] : (vs[m - 1] + vs[m]) / 2;
  }

  /* 按年数切数据（切到的窗口内重画，纵轴随之自适应）
     insight 图走 d.series，指标卡走 d.hist，两者点格式都是 [日期串, 值] */
  function slicedChart(id, years) {
    if (!years) return null;
    const card = cardById.get(id);
    const d = card || B.charts[id];
    if (!d) return null;
    const keep = (arr) => (arr || []).filter((p) => String(p[0]) >= cut);
    const first = d.series ? d.series[0].points : d.hist;
    if (!first || first.length < 2) return null;
    const last = String(first[first.length - 1][0]);
    const cut = String(Number(last.slice(0, 4)) - years) + last.slice(4);
    if (d.series) {
      const series = d.series.map((se) => Object.assign({}, se, { points: keep(se.points) }));
      const kept = series[0].points;
      if (kept.length < 2) return null;
      const data = Object.assign({}, d, { series, window: years });
      // 带均值线的图：用窗口内点实时重算 bands（点太少则保留原线）
      if (d.bands) {
        const nb = bandStatsOf(kept.map((p) => p[1]), d.bands.log);
        if (nb) data.bands = nb;
      }
      // 带中位数线的图：同理跟窗口走
      if (d.median !== undefined && d.median !== null) {
        const md = medianOf(kept.map((p) => p[1]));
        if (md !== null) data.median = md;
      }
      return { kind: 'insight', data, kept };
    }
    const kept = keep(d.hist);
    if (kept.length < 2) return null;
    const cdata = Object.assign({}, d, { hist: kept, window: years });
    if (d.bands) {
      const nb = bandStatsOf(kept.map((p) => p[1]), d.bands.log);
      if (nb) cdata.bands = nb;
    }
    return { kind: 'card', data: cdata, kept };
  }

  function setRange(id, years) {
    const card = document.getElementById('chart-' + id);
    const holder = card && card.querySelector('[data-chart]');
    if (!holder) return;
    initChart(id, holder);
    const chart = instanceById.get(id);
    if (!chart) return;
    const sliced = slicedChart(id, years);
    let opt;
    if (sliced && sliced.kind === 'card') opt = cardOption(sliced.data);
    else {
      const build = builders[id];
      opt = sliced && build ? build(holder, sliced.data) : chartOption(id);
    }
    if (opt) chart.setOption(Object.assign(opt, { animation: false }), { notMerge: true });
    const tip = card.querySelector('.tab-delta');
    if (tip) {
      const k = sliced ? sliced.kept : [];
      const cd = cardById.get(id);
      const diffMode = (cd && cd.delta_mode === 'diff') || (k.length > 1 && !(k[0][1] > 0));
      const sfx = cd ? deltaSuffix(cd) : (diffMode ? 'pp' : '%');
      const nd = deltaDigits(cd);
      // diff 口径（百分点/点差序列）永远显示差值；pct 口径起点为正显示涨跌幅，
      // 起点≤0（跨零的利差等）改用差值，避免除负数/零得出误导数字
      tip.textContent = years && k.length > 1
        ? (diffMode
          ? `近 ${years} 年 ${signed(k[k.length - 1][1] - k[0][1], sfx, nd)}`
          : `近 ${years} 年 ${signed((k[k.length - 1][1] / k[0][1] - 1) * 100, sfx, nd)}`)
        : '';
    }
  }

  /* 图卡顶部的一行摘要：最新值 + 涨跌 + 10 年分位 + 数据日期 */
  function cardStatsHTML(c) {
    const sfx = deltaSuffix(c);
    const nd = deltaDigits(c);
    const items = (c.changes || [])
      .filter((x) => x.value !== null && x.value !== undefined)
      .map((x) => {
        const cls = x.value > 0 ? 'pos' : x.value < 0 ? 'neg' : '';
        return `<span class="delta">${x.label} <b class="${cls}">${signed(x.value, sfx, nd)}</b></span>`;
      });
    const p10 = c.pct && c.pct['10y'];
    if (p10 !== null && p10 !== undefined) {
      /* 光秃的 98% 会被当成买卖信号：>=80% / <=20% 加一句位置描述，只说位置、不给方向 */
      const tag = p10 >= 80 ? ' · 历史极值区' : p10 <= 20 ? ' · 历史低位区' : '';
      items.push(`<span class="delta">10 年分位 <b>${p10.toFixed(0)}%</b>${tag}</span>`);
    }
    return `<div class="chart-stats">
          <span class="v num">${fmtNum(c.value, fmtDigits(c))}</span>
          <span class="u">${c.unit || ''}</span>
          ${items.join('')}
          <span class="asof">${c.date || ''}</span>
        </div>`;
  }

  function fmtDigits(c) {
    if (c.unit_key === 'percent') return 2;
    if (c.unit_key === 'trillion_usd') return 2;
    if (c.unit_key === 'contracts' || c.unit_key === 'tons' || c.unit_key === 'billion_usd') return 0;
    if (c.unit_key === 'cny_per_usd') return 3;
    const a = Math.abs(c.value);
    return a >= 1000 ? 0 : a >= 10 ? 1 : 2;
  }

  /* ----------------------------------------------------------- 板块渲染 */
  /* 模板里 #section-first / #chart-grid / #sections-rest 本来就是最终顺序
     （金价走势 → 历史洞察 → 其余板块），JS 只负责填空，不再搬运 DOM */
  function renderSections() {
    const firstBox = document.getElementById('section-first');
    const restBox = document.getElementById('sections-rest');
    if (!firstBox || !restBox) return;
    const noOf = new Map(ITEMS.filter((it) => it.type === 'section').map((it) => [it.sec.key, it.no]));
    const htmlFor = (s) => {
        const st = s.state || {};
        const tone = verdictTone(st.verdict);
        const panel = (st.points || [])
          .map(
            (p) => `
          <div class="state-item">
            <div class="k"><span>${p.label}</span>${p.date ? `<span class="asof">截至 ${p.date.slice(5)}</span>` : ''}</div>
            <div class="v" data-tone="${p.tone || 'neutral'}">${p.value}</div>
            <div class="t">${p.text}</div>
          </div>`
          )
          .join('');
        // 板块主体统一是图卡网格（样式与「历史洞察」同一套）
        const body = `<div class="charts" data-chart-grid="${s.key}"></div>`;
        return `
        <section class="section" id="${s.anchor}">
          <div class="section-head">
            <div class="section-index">${noOf.get(s.key) || ''}</div>
            <div class="section-title">
              <h2>${s.title}</h2>
              <p>${s.subtitle}</p>
            </div>
            <div class="verdict" data-tone="${tone}"><span class="dot"></span>当前：${st.verdict || '—'}</div>
          </div>
          ${panel ? `<div class="state-panel">${panel}</div>` : ''}
          ${body}
        </section>`;
      };
    const secs = B.sections || [];
    firstBox.innerHTML = secs.length ? htmlFor(secs[0]) : '';
    restBox.innerHTML = secs.slice(1).map(htmlFor).join('');
  }

  function verdictTone(v) {
    if (!v) return 'neutral';
    if (/利多|过热|滞胀|衰退/.test(v)) return v === '过热' ? 'bad' : 'good';
    if (/利空/.test(v)) return 'bad';
    if (/中性|—/.test(v)) return 'neutral';
    return 'warn';
  }

  /* --------------------------------------------------------- 图表公共项 */
  const WIDE = new Set(['gold_long_log', 'cny_gold', 'shanghai_premium', 'gold_annual',
    'asset_returns', 'gold_correlation', 'cb_net_quarterly', 'gold_drawdown', 'gold_bullbear', 'gpr_threat']);

  /* 带时间窗口 tab 的图：连续走势折线图默认都有（近 1 年 / 近 5 年 / 全部）；
     年度柱状、截面矩阵、牛熊周期三类不适合按年切片，排除在外 */
  const NO_RANGE = new Set(['gold_bullbear', 'gold_annual', 'asset_returns', 'cb_net_quarterly', 'gold_correlation']);
  const RANGES = [['近 1 年', 1], ['近 5 年', 5], ['全部', null]];

  function hasRangeTabs(id) {
    if (NO_RANGE.has(id)) return false;
    if (cardById.has(id)) return true;
    const d = B.charts[id];
    return !!builders[id] && !!d && !!d.series;
  }

  function axisCommon(extra) {
    return Object.assign({
      axisLine: { lineStyle: { color: C.line } },
      axisTick: { show: false },
      axisLabel: { color: C.muted, fontSize: 10.5, fontFamily: FONT, hideOverlap: true },
      splitLine: { lineStyle: { color: '#f1ecdf' } },
    }, extra || {});
  }

  const LOG_FMT = (v) => {
    const a = Math.abs(v);
    // 千位保留一位小数：否则轴顶 1,250 和刻度 1,000 都显示成 "1k"，同一条轴上出现两个相同的标签
    if (a >= 1000) {
      const k = v / 1000;
      return (Math.abs(k) >= 10 ? Math.round(k) : +k.toFixed(1)) + 'k';
    }
    if (a >= 100) return v.toFixed(0);
    if (a >= 10) return v.toFixed(0);
    if (a >= 1) return v.toFixed(1);
    if (a >= 0.1) return v.toFixed(2);
    return v.toFixed(3);
  };

  /* 'YYYY' / 'YYYY-MM' / 'YYYY-MM-DD' → UTC 毫秒（时间轴用） */
  function toMs(d) {
    const q = String(d).split('-');
    return Date.UTC(+q[0], q[1] ? +q[1] - 1 : 0, q[2] ? +q[2] : 1);
  }
  const timeData = (pts) => pts.map((q) => [toMs(q[0]), q[1]]);

  /* 悬停显示历史分位：该点超过了全历史百分之几的时点（与卡片上的 10 年分位同口径，窗口为全历史） */
  function rankTip(params, rankValues, unit, scope) {
    const arr = Array.isArray(params) ? params : [params];
    if (!arr.length) return '';
    const head = arr[0].axisValueLabel || arr[0].name || '';
    const body = arr.map((p) => {
      const raw = Array.isArray(p.value) ? p.value[1] : p.value;
      const txt = (raw === null || raw === undefined)
        ? '—' : fmtNum(raw, Math.abs(raw) >= 1000 ? 0 : 2) + unit;
      let line = `${p.marker || ''}${p.seriesName || ''} <b>${txt}</b>`;
      const vs = rankValues[p.seriesIndex] || rankValues[0] || [];
      if (vs.length >= 8 && raw !== null && raw !== undefined) {
        const below = vs.reduce((n, x) => n + (x < raw ? 1 : 0), 0);
        line += `<br/><span style="color:${C.muted};font-size:11px">${scope || '历史'}分位 ${Math.round(below / vs.length * 100)}%</span>`;
      }
      return line;
    }).join('<br/>');
    return (head ? head + '<br/>' : '') + body;
  }

  /* 窗口内实时算均值±1.5σ（与服务端同口径：样本标准差，分母 n-1；点太少返回 null 调用方保留旧线）
     log=true 时在对数空间算再取指数（几何均值）：跨数量级的比值/价格，算术下界会算出负数，
     在对数轴上根本画不出来。 */
  function bandStatsOf(values, log) {
    const vs = (values || []).filter((v) => typeof v === 'number' && !Number.isNaN(v) && (!log || v > 0));
    if (vs.length < 8) return null;
    const xs = log ? vs.map(Math.log) : vs;
    const mu = xs.reduce((a, b) => a + b, 0) / xs.length;
    const sd = Math.sqrt(xs.reduce((a, b) => a + (b - mu) * (b - mu), 0) / (xs.length - 1));
    if (!(sd > 0)) return null;
    const back = log ? Math.exp : (v) => v;
    return { mean: back(mu), up: back(mu + 1.5 * sd), dn: back(mu - 1.5 * sd), k: 1.5, log: !!log };
  }

  function baseOption(opts) {
    const { series, dual, log, unit, units, legend, time, noYGrid, rankValues, rankScope } = opts;
    const o = {
      animationDuration: 500,
      textStyle: { fontFamily: FONT },
      grid: { left: 8, right: dual ? 8 : 14, top: legend === false ? 16 : 38, bottom: 6, containLabel: true },
      tooltip: rankValues ? {
        trigger: 'axis',
        backgroundColor: 'rgba(255,255,255,.97)',
        borderColor: C.line,
        borderWidth: 1,
        padding: [8, 11],
        textStyle: { color: C.ink, fontSize: 12, fontFamily: FONT },
        axisPointer: { type: 'line', lineStyle: { color: C.gold, width: 1, type: 'dashed' } },
        formatter: (p) => rankTip(p, rankValues, unit || '', rankScope),
      } : units ? {
        trigger: 'axis',
        backgroundColor: 'rgba(255,255,255,.97)',
        borderColor: C.line,
        borderWidth: 1,
        padding: [8, 11],
        textStyle: { color: C.ink, fontSize: 12, fontFamily: FONT },
        axisPointer: { type: 'line', lineStyle: { color: C.gold, width: 1, type: 'dashed' } },
        /* 双轴图：每个系列自带单位后缀（左轴万亿 vs 右轴美元/盎司，不可共用一个 unit） */
        formatter: (params) => {
          const arr = Array.isArray(params) ? params : [params];
          if (!arr.length) return '';
          const head = arr[0].axisValueLabel || arr[0].name || '';
          const body = arr.map((q) => {
            const raw = Array.isArray(q.value) ? q.value[1] : q.value;
            const u = units[q.seriesIndex] || unit || '';
            const txt = (raw === null || raw === undefined)
              ? '—' : fmtNum(raw, Math.abs(raw) >= 1000 ? 0 : 2) + u;
            return `${q.marker || ''}${q.seriesName || ''} <b>${txt}</b>`;
          }).join('<br/>');
          return (head ? head + '<br/>' : '') + body;
        },
      } : {
        trigger: 'axis',
        backgroundColor: 'rgba(255,255,255,.97)',
        borderColor: C.line,
        borderWidth: 1,
        padding: [8, 11],
        textStyle: { color: C.ink, fontSize: 12, fontFamily: FONT },
        axisPointer: { type: 'line', lineStyle: { color: C.gold, width: 1, type: 'dashed' } },
        valueFormatter: (v) => (v === null || v === undefined ? '—' : fmtNum(v, Math.abs(v) >= 1000 ? 0 : 2) + (unit || '')),
      },
      xAxis: axisCommon(time ? {
        type: 'time',
        splitLine: { show: false },
        axisLabel: { color: C.muted, fontSize: 10.5, fontFamily: FONT, hideOverlap: true },
      } : {
        type: 'category',
        boundaryGap: opts.bar === true,
        splitLine: { show: false },
        axisLabel: { color: C.muted, fontSize: 10.5, fontFamily: FONT, hideOverlap: true, formatter: opts.xFormat },
      }),
      yAxis: [],
    };
    if (legend !== false) {
      o.legend = {
        top: 0, left: 0, itemWidth: 14, itemHeight: 8, itemGap: 14,
        textStyle: { color: C.ink2, fontSize: 11.5, fontFamily: FONT },
        icon: 'roundRect',
      };
    }
    const y1 = axisCommon({ type: log ? 'log' : 'value', scale: !log, position: 'left',
      ...(noYGrid ? { splitLine: { show: false } } : null) });
    if (log) {
      y1.logBase = 10;
      y1.axisLabel.formatter = LOG_FMT;
      // ECharts 对数轴默认把范围对齐到整十数量级：86–130 会变成 10–1000，曲线被压成一条直线。
      // 改成按数据自身的对数跨度给 8% 余量，留白与图表高度成比例。
      const vals = [];
      (opts.rangeValues || []).forEach((v) => {
        if (typeof v === 'number' && isFinite(v) && v > 0) vals.push(v);
      });
      series.forEach((s) => {
        if ((s.yAxisIndex || 0) !== 0) return;
        (s.data || []).forEach((d) => {
          const v = Array.isArray(d) ? d[d.length - 1] : d;
          if (typeof v === 'number' && isFinite(v) && v > 0) vals.push(v);
        });
      });
      if (vals.length > 1) {
        const lo = Math.min(...vals);
        const hi = Math.max(...vals);
        const pad = Math.log(hi / lo) * 0.08;
        y1.min = lo / Math.exp(pad);
        y1.max = hi * Math.exp(pad);
      }
    }
    o.yAxis.push(y1);
    if (dual) {
      const y2 = axisCommon({ type: 'value', scale: true, position: 'right', splitLine: { show: false } });
      o.yAxis.push(y2);
    }
    o.series = series;
    o.dataZoom = [{ type: 'inside', throttle: 60, zoomOnMouseWheel: 'shift', moveOnMouseWheel: false }];
    return o;
  }

  function lineSeries(name, points, extra) {
    return Object.assign({
      name,
      type: 'line',
      data: points.map((p) => p[1]),
      showSymbol: false,
      symbol: 'circle',
      symbolSize: 4,
      lineStyle: { width: 1.6 },
      emphasis: { focus: 'series' },
      sampling: 'lttb',
    }, extra || {});
  }

  const categories = (pts) => pts.map((p) => p[0]);

  /* ------------------------------------------------- 牛熊周期图：段末标注
     每段各自从 0% 起算，峰谷处标「日期 · 月数 · 本段累计 · 年化」。
     ECharts 的 endLabel / label 没有避让能力（hideOverlap 会直接丢标签），
     所以在 canvas 上盖一层 DOM：先量真实尺寸，再按候选位置逐个避让。
     卡片里只标大段（label_min），⤢ 放大后全部展开。 */
  const sgnPct = (v, d) => (v > 0 ? '+' : '') + v.toFixed(d === undefined ? 0 : d) + '%';

  function placeCycleLabels(chart, holder, d) {
    let layer = holder.querySelector('.chart-labels');
    if (!layer) {
      layer = el('div', 'chart-labels');
      holder.appendChild(layer);
    }
    layer.textContent = '';
    const W = holder.clientWidth, H = holder.clientHeight;
    if (!W || !H || !d.legs) return;
    const card = holder.closest('.chart-card');
    const zoomed = !!(card && card.classList.contains('zoom'));
    const minCum = zoomed ? 0 : (d.label_min || 0);
    const grid = chart.getModel().getComponent('grid').coordinateSystem.getRect();
    const BOUND = { l: 2, t: 2, r: W - 2, b: Math.min(H - 2, grid.y + grid.height + 18) };

    const curve = [];
    const items = [];
    d.legs.forEach((lg) => {
      lg.points.forEach((pt) => {
        const q = chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [pt[0], pt[1]]);
        if (q) curve.push(q);
      });
      if (Math.abs(lg.cum) < minCum) return;
      const last = lg.points[lg.points.length - 1];
      const p = chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [last[0], last[1]]);
      if (!p) return;
      const node = el('div', 'lbl ' + lg.kind);
      node.innerHTML = '<div>' + lg.end + (lg.ongoing ? '（进行中）' : '') + '</div>' +
        '<div class="d">' + lg.months + 'm · ' + sgnPct(lg.cum) + '</div>' +
        '<div class="d">' + sgnPct(lg.ann) + '/yr</div>';
      node.style.visibility = 'hidden';
      node.style.left = '-9999px';
      layer.appendChild(node);
      items.push({ node: node, p: p, bull: lg.kind === 'bull' });
    });

    const taken = [];
    items.forEach((it) => {
      const w = it.node.offsetWidth, h = it.node.offsetHeight;
      const gap = 7;
      const dy0 = it.bull ? -(gap + h) : gap;
      const cands = [];
      [0, 16, 34, 56, 84, 116].forEach((extra) => {
        [0, 0.6, -0.6, 1.15, -1.15].forEach((k) => {
          cands.push([k * w * 0.5, dy0 + (it.bull ? -extra : extra)]);
        });
      });
      let best = null;
      for (let i = 0; i < cands.length; i++) {
        const x = it.p[0] + cands[i][0] - w / 2;
        const y = it.p[1] + cands[i][1];
        if (x < BOUND.l || x + w > BOUND.r || y < BOUND.t || y + h > BOUND.b) continue;
        const r = { l: x, t: y, r: x + w, b: y + h };
        let score = i * 0.8;
        taken.forEach((t) => {
          const ox = Math.min(r.r, t.r) - Math.max(r.l, t.l);
          const oy = Math.min(r.b, t.b) - Math.max(r.t, t.t);
          if (ox > 0 && oy > 0) score += ox * oy * 0.5 + 200;
        });
        curve.forEach((c) => {
          if (c[0] > r.l + 1 && c[0] < r.r - 1 && c[1] > r.t + 1 && c[1] < r.b - 1) score += 30;
        });
        if (score === 0) { best = { x: x, y: y, r: r }; break; }
        if (!best || score < best.score) best = { score: score, x: x, y: y, r: r };
      }
      if (best) {
        taken.push(best.r);
        it.node.style.left = best.x + 'px';
        it.node.style.top = best.y + 'px';
        it.node.style.visibility = '';
      } else {
        it.node.style.display = 'none';
      }
    });
  }

  function attachCycleLabels(chart, holder, d) {
    const place = () => placeCycleLabels(chart, holder, d);
    chart.on('finished', place);
    chart.on('datazoom', () => setTimeout(place, 0));
    if (window.ResizeObserver) {
      let t = null;
      new ResizeObserver(() => {
        clearTimeout(t);
        t = setTimeout(place, 90);
      }).observe(holder);
    }
    place();
  }

  /* ------------------------------------------------------------- 各图表 */
  const builders = {
    /* 金价：1971–2000 月度定盘价 + 之后日线，必须用时间轴
       （类目轴每条观测等宽，会把 26 年日线拉成 95% 宽度、把前面 30 年压成一条竖线）。
       刻度交给 ECharts 按跨度自己取（年 / 季 / 月 / 日），窗内纵轴仍然自适应。 */
    gold_long_log(el2, d) {
      const pts = d.series[0].points;
      const marks = (d.marks || []).map(([date, label], i) => ({
        xAxis: toMs(date),
        label: {
          formatter: label, position: i % 2 === 0 ? 'insideEndTop' : 'insideEndBottom',
          color: C.muted, fontSize: 10, fontFamily: FONT, distance: 8, rotate: 0,
        },
        lineStyle: { color: C.goldBright, type: 'dashed', width: 1 },
      }));
      const o = baseOption({
        series: [lineSeries('金价', pts, {
          data: timeData(pts),
          itemStyle: { color: C.gold },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(212,168,83,.22)' }, { offset: 1, color: 'rgba(212,168,83,0)' }] } },
          markLine: { symbol: 'none', silent: true, data: marks, animation: false },
        })],
        log: true,
        time: true,
        unit: ' 美元/盎司',
        legend: false,
        rankValues: [pts.map((p) => p[1])],
        rankScope: d.window ? `近 ${d.window} 年` : '历史',
      });
      o.grid.top = 26;
      if (d.window) {
        // 窗口内刻度交给 ECharts 按跨度取（1 年是月、5 年是季/年）
        // 纵轴不能还是整数量级（否则 1 年的波动被压成一条直线）
        const vs = pts.map((p) => p[1]);
        const lo = Math.min(...vs);
        const hi = Math.max(...vs);
        const pad = (hi - lo) * 0.12 || hi * 0.02;
        o.yAxis[0].min = Math.max(0.001, lo - pad);
        o.yAxis[0].max = hi + pad;
      } else {
        // 55 年全历史：默认会把刻度均分成 1980 / 1989 / 1998 这种非整十年份，钳成十年一格
        const decade = 10 * 365.25 * 24 * 3600 * 1000;
        o.xAxis.minInterval = decade;
        o.xAxis.maxInterval = decade;
      }
      return o;
    },

    cny_gold(el2, d) {
      const pts = d.series[0].points;
      const o = baseOption({
        series: [lineSeries('人民币金价', pts, {
          data: timeData(pts),
          itemStyle: { color: C.teal },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(47,111,106,.20)' }, { offset: 1, color: 'rgba(47,111,106,0)' }] } },
        })],
        log: true, time: true, unit: ' 元/克', legend: false,
        rankValues: [pts.map((p) => p[1])],
        rankScope: d.window ? `近 ${d.window} 年` : '历史',
      });
      o.grid.top = 26;
      return o;
    },

    shanghai_premium(el2, d) {
      const pts = d.series[0].points;
      const o = baseOption({
        series: [lineSeries('溢价', pts, {
          itemStyle: { color: C.blue },
          areaStyle: { color: 'rgba(67,104,155,.10)' },
          markLine: (() => {
            const data = [{ yAxis: 0 }, ...bandLines(d.bands)];
            return {
              symbol: 'none', silent: true, animation: false, data,
              lineStyle: { color: C.muted, type: 'dashed', width: 1 }, label: { show: false },
            };
          })(),
        })],
        unit: '%', legend: false,
        noYGrid: !!d.bands,
        rankValues: [pts.map((p) => p[1])],
        rankScope: d.window ? `近 ${d.window} 年` : '历史',
      });
      o.xAxis.data = categories(pts);
      o.xAxis.axisLabel.formatter = (v) => String(v).slice(0, 7);
      return o;
    },

    gpr_threat(el2, d) {
      const pts = d.series[0].points;
      const o = baseOption({
        series: [lineSeries('GPR 威胁指数', pts, {
          itemStyle: { color: C.blue },
          areaStyle: { color: 'rgba(67,104,155,.10)' },
          markLine: (() => {
            const data = [{ yAxis: 100, label: { formatter: '历史常态 100', color: C.muted, fontSize: 10, position: 'insideEndTop' } }, ...bandLines(d.bands)];
            return {
              symbol: 'none', silent: true, animation: false, data,
              lineStyle: { color: C.muted, type: 'dashed', width: 1 }, label: { show: false },
            };
          })(),
        })],
        unit: '', legend: false,
        noYGrid: !!d.bands,
        rankValues: [pts.map((p) => p[1])],
        rankScope: d.window ? `近 ${d.window} 年` : '历史',
      });
      o.xAxis.data = categories(pts);
      // 月频、跨 40 年：只留年份，否则刻度会印成 1985-01 这种没人读的串
      o.xAxis.axisLabel.formatter = (v) => String(v).slice(0, 4);
      return o;
    },

    gold_bullbear(el2, d) {
      const legs = d.legs || [];
      const series = legs.map((lg) => {
        const bull = lg.kind === 'bull';
        const color = bull ? C.up : C.down;
        return {
          name: bull ? '上涨周期' : '下跌周期',
          type: 'line',
          data: lg.points,
          showSymbol: false, symbol: 'circle', symbolSize: 4,
          lineStyle: { width: 1.5, color: color },
          itemStyle: { color: color },
          areaStyle: { color: color, opacity: 0.10 },
          emphasis: { focus: 'none' },
          z: 3,
        };
      });
      if (!series.length) return null;
      series[0].markLine = {
        symbol: 'none', silent: true, animation: false, label: { show: false },
        lineStyle: { color: C.muted, width: 1 }, data: [{ yAxis: 0 }],
      };

      const o = baseOption({ series, unit: '%', time: true });
      o.xAxis.max = d.xmax;
      o.xAxis.axisLabel.formatter = (v) => String(new Date(v).getUTCFullYear());
      o.yAxis[0].axisLabel.formatter = (v) => (Math.abs(v) < 0.5 ? '0%' : sgnPct(v));
      if (o.legend) o.legend.data = ['上涨周期', '下跌周期'];
      o.tooltip.formatter = (ps) => {
        const p = (ps || []).find((x) => x.value != null);
        if (!p) return '';
        const lg = legs[p.seriesIndex];
        if (!lg) return '';
        const ms = p.value[0], pct = p.value[1], price = p.value[2];
        const dt = new Date(ms);
        const day = dt.getUTCFullYear() + '-' + String(dt.getUTCMonth() + 1).padStart(2, '0');
        const color = lg.kind === 'bull' ? C.up : C.down;
        return '<b>' + day + '</b><br/>' +
          '点位 <b>' + fmtNum(price, 1) + '</b> 美元/盎司<br/>' +
          '本段至此 <b style="color:' + color + '">' + sgnPct(pct, 1) + '</b><br/>' +
          '状态 <b style="color:' + color + '">' + (lg.kind === 'bull' ? '上涨周期' : '下跌周期') + '</b>' +
          (lg.ongoing ? ' <span style="color:' + C.muted + '">· 未确认</span>' : '') + '<br/>' +
          '<span style="color:' + C.muted + '">本轮</span> ' + lg.start + ' → ' + lg.end + ' · ' + lg.months + ' 个月<br/>' +
          '<span style="color:' + C.muted + '">本轮累计</span> <b style="color:' + color + '">' + sgnPct(lg.cum, 1) + '</b><br/>' +
          '<span style="color:' + C.muted + '">年化</span> <b>' + sgnPct(lg.ann, 1) + '</b>';
      };
      o.__after = (chart, holder) => attachCycleLabels(chart, holder, d);
      return o;
    },

    gold_drawdown(el2, d) {
      const pts = d.series[0].points;
      const o = baseOption({
        series: [lineSeries('回撤', pts, {
          itemStyle: { color: C.down },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(44,122,84,.05)' }, { offset: 1, color: 'rgba(44,122,84,.30)' }] } },
        })],
        unit: '%', legend: false,
        rankValues: [pts.map((p) => p[1])],
        rankScope: d.window ? `近 ${d.window} 年` : '历史',
      });
      o.xAxis.data = categories(pts);
      o.xAxis.axisLabel.formatter = (v) => String(v).slice(0, 4);
      return o;
    },

    gold_annual(el2, d) {
      const pts = d.series[0].points;
      const o = baseOption({
        bar: true,
        series: [{
          name: '年度涨跌幅',
          type: 'bar',
          barCategoryGap: '22%',
          data: pts.map((p) => ({
            value: p[1],
            itemStyle: { color: p[1] >= 0 ? C.up : '#b9b2a1', borderRadius: p[1] >= 0 ? [2, 2, 0, 0] : [0, 0, 2, 2] },
          })),
        }],
        unit: '%', legend: false,
      });
      o.xAxis.data = categories(pts);
      o.xAxis.axisLabel.interval = 9;
      o.grid.top = 22;
      return o;
    },

    cb_net_quarterly(el2, d) {
      const pts = d.series[0].points;
      const o = baseOption({
        bar: true,
        series: [{
          name: '季度净变动',
          type: 'bar',
          barCategoryGap: '28%',
          data: pts.map((p) => {
            const prov = String(p[0]).endsWith('*');
            return {
              value: p[1],
              itemStyle: {
                color: p[1] >= 0 ? C.up : '#b9b2a1',
                opacity: prov ? 0.45 : 1,
                borderRadius: p[1] >= 0 ? [2, 2, 0, 0] : [0, 0, 2, 2],
              },
            };
          }),
        }],
        unit: '吨', legend: false,
      });
      o.xAxis.data = categories(pts);
      o.xAxis.axisLabel.interval = 7;
      o.grid.top = 22;
      return o;
    },

    gold_correlation(el2, d) {
      /* 相关系数 -1~1，大部分格子落在浅色中间带（|v| 小）——白字看不清。
         按 |v| 逐格选字色：浅底用墨字（白描边保底），深底用白字（深描边保底），
         阈值 0.4：当前数据里 0.48/0.74/0.84/1 走白字，其余走墨字。 */
      const heatLabel = (v) => (Math.abs(v) < 0.4
        ? { color: '#1f1a12', textBorderColor: 'rgba(255,255,255,.7)', textBorderWidth: 1 }
        : { color: '#fff', textBorderColor: 'rgba(60,50,35,.55)', textBorderWidth: 1 });
      const o = baseOption({
        series: [{
          name: '相关系数',
          type: 'heatmap',
          // y 轴翻转后，第 0 行（Au9999）对应 y 下标 6：建 data 时直接重排 y 坐标
          data: d.heat.map((h) => ({
            value: [h[0], d.assets.length - 1 - h[1], h[2]],
            label: heatLabel(h[2]),
          })),
          label: {
            show: true,
            fontSize: 11,
            fontWeight: 500,
            formatter: (p) => p.value[2].toFixed(3).replace('1.000', '1'),
          },
          itemStyle: { borderColor: '#f7f3ea', borderWidth: 2 },
          emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,.35)' } },
        }],
        legend: false,
      });
      o.xAxis = {
        type: 'category', data: d.assets,
        axisLabel: { interval: 0, rotate: 24, fontSize: 11, color: '#5c5546' },
        axisLine: { show: false }, axisTick: { show: false },
      };
      o.yAxis = {
        type: 'category', data: [...d.assets].reverse(),
        axisLabel: { fontSize: 11, color: '#5c5546' },
        axisLine: { show: false }, axisTick: { show: false },
      };
      // y 轴翻转已在 data 里处理，这里不再重排
      o.visualMap = {
        min: d.vmin, max: d.vmax, show: false, calculable: false,
        inRange: { color: ['#2f6db3', '#f7f3ea', '#b03a2e'] },
      };
      o.tooltip = {
        trigger: 'item',
        backgroundColor: 'rgba(255,255,255,.97)',
        borderColor: C.line,
        borderWidth: 1,
        padding: [8, 11],
        textStyle: { color: C.ink, fontSize: 12 },
        formatter: (p) => `${d.assets[d.assets.length - 1 - p.value[1]]} × ${d.assets[p.value[0]]}<br/><b>${p.value[2].toFixed(3)}</b>`,
      };
      o.grid.top = 78;
      o.grid.bottom = 8;
      return o;
    },

    asset_returns(el2, d) {
      const wins = d.windows;
      const colors = [C.goldBright, '#95a7bb', '#5f7fa3', '#a98a6b', '#c3b49a', '#d8d2c4', '#7fa89b'];
      const series = d.rows.map((row, ri) => ({
        name: row.name,
        type: 'bar',
        barGap: '12%',
        itemStyle: { color: colors[ri % colors.length] },
        data: row.values.map((v, ci) => {
          const best = Math.max(...d.rows.map((r) => (r.values[ci] === null ? -Infinity : r.values[ci])));
          return {
            value: v,
            itemStyle: { borderRadius: v >= 0 ? [2, 2, 0, 0] : [0, 0, 2, 2] },
            label: { show: v !== null && v === best, position: 'top', formatter: '最佳', color: C.gold, fontSize: 9.5, fontWeight: 600 },
          };
        }),
      }));
      const o = baseOption({ series, unit: '%', bar: true });
      o.xAxis.data = wins;
      o.grid.top = 34;
      return o;
    },

    gold_ma_gap(el2, d) {
      const pts = d.series[0].points;
      const b = d.bands;
      const f = (v) => (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
      const up = b ? b.up : 10;
      const dn = b ? b.dn : -10;
      /* 偏离度是围绕零轴往返的振荡量，不是「涨/跌两态」——
         所以不用红绿双色（那是牛熊周期图的语言，两套红色会被读成同一件事），
         改用：单色线 + 零点为基线的面积 + 极端带阴影。
         读法是「离 200 日均线多远」和「在带内还是带外」，不是「现在多/空」。 */
      const o = baseOption({
        series: [lineSeries('200 日均线偏离度', pts, {
          itemStyle: { color: C.ink2 },
          lineStyle: { width: 1, color: C.ink2 },
          areaStyle: { origin: 0, color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: 'rgba(184,148,46,.34)' },
                         { offset: 0.5, color: 'rgba(184,148,46,.16)' },
                         { offset: 1, color: 'rgba(184,148,46,.34)' }] } },
          markArea: undefined,
          markLine: (() => {
            const zero = { yAxis: 0, lineStyle: { color: C.muted, type: 'solid', width: 1 }, label: { show: false } };
            const dot = (y, color, text, pos) => ({
              yAxis: y, lineStyle: { color, type: 'dotted', width: 1 },
              // 白底托一下：标签所在高度上总会有线穿过去，不托底就看不清
              label: { formatter: text, color, fontSize: 10, position: pos,
                       backgroundColor: 'rgba(255,255,255,.82)', padding: [1, 2] },
            });
            // 有统计锚就用它（阈值随品种走，语义不变：拉伸 / 超跌）
            if (!b) return { symbol: 'none', silent: true, animation: false,
              data: [zero, dot(10, C.up, '拉伸 +10%', 'insideEndTop'), dot(-10, C.down, '超跌 -10%', 'insideEndBottom')] };
            return { symbol: 'none', silent: true, animation: false, data: [
              zero,
              { yAxis: b.mean, lineStyle: { color: '#6f6350', type: 'dashed', width: 1 }, label: { show: false } },
              dot(b.up, C.up, '拉伸 ' + f(b.up), 'insideEndTop'),
              dot(b.dn, C.down, '超跌 ' + f(b.dn), 'insideEndBottom'),
            ] };
          })(),
        })],
        unit: '%', legend: false,
        noYGrid: !!d.bands,
        rankValues: [pts.map((p) => p[1])],
        rankScope: d.window ? `近 ${d.window} 年` : '历史',
      });
      o.xAxis.data = categories(pts);
      o.xAxis.axisLabel.formatter = (v) => String(v).slice(0, 4);
      /* 纵轴钳到数据范围：0 和 +5% 两条参考线挤在默认 -30~40 的中间看不出差，
         而且上方大片空白会把“离趋势多远"压扁 */
      const vals = pts.map((p) => p[1]);
      const lo = Math.min(...vals, dn);
      const hi = Math.max(...vals, up);
      o.yAxis[0].min = Math.floor((lo - 3) / 10) * 10;
      o.yAxis[0].max = Math.ceil((hi + 3) / 10) * 10;
      o.grid.right = 78;   // 给右侧「拉伸 / 超跌」标签留位置
      return o;
    },

    /* 比特币的黄金计价：1 BTC 值多少盎司黄金。单轴比值（不再是双轴价格对比），
       对数轴下单边采用趋势与几次轮动拐点都能读。均值与 ±1.5σ 与其他图同一套视觉语言，
       但必须在对数空间算：比值跨两个数量级，算术下界会算出负的盎司数。 */
    gold_vs_btc(el2, d) {
      const r = d.series[0];
      const b = d.bands;
      const oz = (v) => (v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2));
      const marks = b ? [
        { yAxis: b.mean, lineStyle: { color: '#6f6350', type: 'solid', width: 1.5 }, label: { show: false } },
        { yAxis: b.up, lineStyle: { color: C.up, type: 'dotted', width: 1 }, label: { formatter: '拉伸 ' + oz(b.up) + ' 盎司', color: C.up, fontSize: 10, position: 'insideEndTop' } },
        { yAxis: b.dn, lineStyle: { color: C.down, type: 'dotted', width: 1 }, label: { formatter: '超跌 ' + oz(b.dn) + ' 盎司', color: C.down, fontSize: 10, position: 'insideEndBottom' } },
      ] : null;
      const series = [lineSeries(r.name, r.points, {
        data: timeData(r.points), itemStyle: { color: C.goldBright },
        lineStyle: { width: 1.8 },
        areaStyle: { color: 'rgba(212,168,83,.10)' },
        markLine: marks ? { symbol: 'none', silent: true, animation: false, data: marks } : undefined,
      })];
      const o = baseOption({
        series, log: true, time: true, unit: ' 盎司', legend: false,
        rangeValues: b ? [b.dn, b.mean, b.up] : [],
      });
      o.grid.right = 92;   // 给右侧「拉伸 / 超跌」标签留位置
      return o;
    },

    gold_oil_ratio(el2, d) {
      const pts = d.series[0].points;
      const o = baseOption({
        series: [lineSeries('金油比', pts, {
          itemStyle: { color: C.teal },
          lineStyle: { width: 1.5 },
          areaStyle: { color: 'rgba(47,111,106,.12)' },
          markLine: {
            symbol: 'none', silent: true, animation: false,
            data: [{
              yAxis: d.median,
              lineStyle: { color: C.muted, type: 'dashed', width: 1 },
              label: { formatter: '中位数 ' + d.median, color: C.muted, fontSize: 10, position: 'insideEndTop' },
            }],
          },
        })],
        log: true, unit: ' 倍', legend: false,
        rankValues: [pts.map((p) => p[1])],
        rankScope: d.window ? `近 ${d.window} 年` : '历史',
      });
      o.xAxis.data = categories(pts);
      o.xAxis.axisLabel.formatter = (v) => String(v).slice(0, 4);
      o.grid.right = 74;   // 给右侧「中位数」标签留位置
      return o;
    },
  };

  /* --------------------------------------------------------- 图表渲染 */
  const instances = [];
  const instanceById = new Map();

  /* 「历史洞察」与各板块同一套头：编号 + 标题 + verdict + 状态条。
     内容来自 B.insights（compute.build_insights_state），锚点 #insights 保持不变。 */
  function renderInsights() {
    const box = document.getElementById('insights-block');
    if (!box || !B.insights) return;
    const item = (ITEMS || []).find((it) => it.type === 'insights');
    const no = item ? item.no : '';
    const ins = B.insights;
    const tone = verdictTone(ins.verdict);
    const panel = (ins.points || [])
      .map(
        (p) => `
      <div class="state-item">
        <div class="k"><span>${p.label}</span>${p.date ? `<span class="asof">截至 ${p.date.slice(5)}</span>` : ''}</div>
        <div class="v" data-tone="${p.tone || 'neutral'}">${p.value}</div>
        <div class="t">${p.text}</div>
      </div>`
      )
      .join('');
    box.innerHTML = `
      <section class="section" id="insights">
        <div class="section-head">
          <div class="section-index">${no}</div>
          <div class="section-title">
            <h2>历史洞察</h2>
            <p>${ins.subtitle || ''}</p>
          </div>
          <div class="verdict" data-tone="${tone}"><span class="dot"></span>当前：${ins.verdict || '—'}</div>
        </div>
        ${panel ? `<div class="state-panel">${panel}</div>` : ''}
        <p class="charts-hint">悬停看数值，点右上角 ⤢ 放大，shift + 滚轮缩放</p>
      </section>`;
  }

  /* 指标卡的 hist → ECharts option（与 builders 出来的图同一套坐标系） */
  /* 均值回归锚：近 10 年均值（虚线）±1.5σ（点线），故意做淡、不抢价格线 */
  function bandLines(b) {
    if (!b) return [];
    const item = (v, color, type, w) => ({
      yAxis: v, symbol: 'none', silent: true,
      lineStyle: { color, type, width: w }, label: { show: false },
    });
    return [
      item(b.mean, '#6f6350', 'solid', 1.5),
      item(b.up, '#a89f8d', 'dotted', 1.25),
      item(b.dn, '#a89f8d', 'dotted', 1.25),
    ];
  }

  function cardOption(card) {
    const pts = card.hist || [];
    if (pts.length < 2) return null;
    const useLog = LOGGABLE.has(card.unit_key) && pts.every((p) => p[1] > 0);
    const zeroLine = card.unit_key === 'percent';
    return baseOption({
      series: [lineSeries(card.name, pts, {
        data: timeData(pts),
        itemStyle: { color: C.gold },
        areaStyle: useLog ? undefined : {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(212,168,83,.24)' },
              { offset: 1, color: 'rgba(212,168,83,0)' },
            ],
          },
        },
        markLine: (() => {
          const data = [...(zeroLine ? [{ yAxis: 0 }] : []), ...bandLines(card.bands)];
          return data.length ? {
            symbol: 'none', silent: true, animation: false, data,
            lineStyle: { color: C.muted, type: 'dashed', width: 1 }, label: { show: false },
          } : undefined;
        })(),
      })],
      log: useLog, time: true, legend: false,
      unit: card.unit ? ' ' + card.unit : '',
      noYGrid: !!card.bands,
      rankValues: [(card.hist || []).map((p) => p[1])],
      rankScope: card.window ? `近 ${card.window} 年` : '历史',
    });
  }

  function initChart(id, holder) {
    if (!holder || instanceById.has(id)) return;
    try {
      const opt = chartOption(id);
      if (!opt) return;
      const chart = echarts.init(holder, null, { renderer: 'canvas' });
      chart.setOption(opt);
      instances.push(chart);
      instanceById.set(id, chart);
      if (typeof opt.__after === 'function') opt.__after(chart, holder);
    } catch (e) {
      console.error('[chart]', id, e);
    }
  }

  function chartOption(id) {
    const card = cardById.get(id);
    if (card) return cardOption(card);
    const build = builders[id];
    return build ? build(null, B.charts[id]) : null;
  }

  function renderCharts() {
    const hosts = [];
    (B.sections || []).forEach((s) => {
      const box = document.querySelector(`[data-chart-grid="${s.key}"]`);
      if (box) hosts.push({ root: box, entries: s.entries || s.charts || [] });
    });
    const main = document.getElementById('chart-grid');
    if (main) hosts.push({ root: main, entries: (B.chart_order || []).map((id) => ({ id, kind: 'insight' })) });
    if (!hosts.length) return;

    /* 不再折叠：每张图都直接展开。之前 >4 张就收进 <details>，但现在只有两个板块
       超过 4 张、且各只多出 1 张，折叠省不了版面，反倒让人以为图被删了。 */
    const entriesHTML = (entries) => entries.map(chartCardHTML).join('');
    hosts.forEach((h) => { h.root.innerHTML = entriesHTML(h.entries); });

    document.querySelectorAll('[data-tabs]').forEach((box) => {
      const id = box.dataset.tabs;
      box.querySelectorAll('button').forEach((btn) => {
        btn.addEventListener('click', () => {
          box.querySelectorAll('button').forEach((b) => b.classList.remove('on'));
          btn.classList.add('on');
          setRange(id, btn.dataset.years ? Number(btn.dataset.years) : null);
        });
      });
    });

    const holders = Array.from(document.querySelectorAll('[data-chart]'));

    // 一页 50+ 张图，一次性全画会卡首屏：先画视口内的，剩下的按帧分批补上
    if (window.echarts) {
      const inView = (h) => h.getBoundingClientRect().top < window.innerHeight * 1.5;
      const queue = holders.slice()
        .sort((a, b) => (inView(b) ? 1 : 0) - (inView(a) ? 1 : 0));
      const step = () => {
        const t0 = performance.now();
        while (queue.length && performance.now() - t0 < 12) {
          const h = queue.shift();
          initChart(h.dataset.chart, h);
        }
        if (queue.length) setTimeout(step, 16);
      };
      step();
    } else {
      window.addEventListener('load', () => holders.forEach((h) => initChart(h.dataset.chart, h)));
    }

    // 打印前先把所有图都初始化一遍，否则纸上少图
    window.addEventListener('beforeprint', () => {
      document.querySelectorAll('[data-chart]').forEach((h) => initChart(h.dataset.chart, h));
      instances.forEach((c) => c.resize());
    });

    // 放大 / 还原
    const toggleZoom = (id, force) => {
      const card = document.getElementById('chart-' + id);
      if (!card) return;
      const holder = card.querySelector('[data-chart]');
      if (holder) initChart(id, holder);
      const chart = instanceById.get(id);
      if (!chart) return;
      const next = force === undefined ? !card.classList.contains('zoom') : force;
      card.classList.toggle('zoom', next);
      document.body.classList.toggle('modal-open', !!document.querySelector('.chart-card.zoom'));
      setTimeout(() => chart.resize(), 60);
    };

    document.querySelectorAll('[data-expand]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleZoom(btn.dataset.expand);
      });
    });

    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      const zoomed = document.querySelector('.chart-card.zoom');
      if (zoomed) toggleZoom(zoomed.id.replace('chart-', ''), false);
    });

    let timer = null;
    window.addEventListener('resize', () => {
      clearTimeout(timer);
      timer = setTimeout(() => instances.forEach((c) => c.resize()), 160);
    });
  }

  /* ------------------------------------------------- 导出模块的内部句柄 */
  /* web/export.js 要把图重排成小红书图卡：图的 option、图卡元数据、数字格式化
     都只有一份定义，导出侧直接复用，避免网页和图片对不上。 */
  window.__BOARD_INTERNALS__ = {
    B, chartOption, cardById, fmtNum, signed, deltaSuffix, deltaDigits, fmtDigits,
  };

  /* ----------------------------------------------------------------- 启动 */
  function boot() {
    renderAlerts();
    renderHero();
    renderNav();
    renderSections();
    renderInsights();
    renderCharts();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
