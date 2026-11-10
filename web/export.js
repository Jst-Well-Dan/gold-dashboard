/* ==========================================================================
   黄金看板 · 小红书图卡导出（web/export.js）
   把看板上的图按 1080×1440（3:4）重排成可直接发小红书的图片。

   关键取舍：图的 option 直接复用 board.js 的 chartOption(id)，只重排字号、
   留白与文字区，不重画数据 —— 保证图上的一切（对数轴、分位线、牛熊带、
   双轴单位）与看板完全一致，不会出现「网页和图片对不上」。

   输出：canvas → PNG dataURL。打包下载用最小化的 store-only ZIP（PNG 本身
   已压缩，再 deflate 没有收益），因此不引入任何第三方依赖。
   ========================================================================== */
(function () {
  'use strict';

  const I = window.__BOARD_INTERNALS__;
  if (!I || !window.echarts) return;

  const { B, chartOption, cardById, fmtNum, signed, deltaSuffix, deltaDigits, fmtDigits } = I;

  /* ----------------------------------------------------------------- 常量 */
  const W = 1080;
  const H = 1440;
  const PAD = 56;
  const INNER = W - PAD * 2;          // 968
  const MAXPICK = 18;                 // 小红书单篇图片上限

  const T = {
    paper: '#f7f5f0', card: '#ffffff', ink: '#1f1a12', ink2: '#4b4437',
    muted: '#8a8375', line: '#e6ddc9', gold: '#a8892a', goldBright: '#d4a853',
    goldSoft: '#e9d7a6', up: '#b8402f', down: '#2c7a54', warn: '#b8791a',
  };
  const SANS = '"PingFang SC","Noto Sans SC","Microsoft YaHei",Inter,sans-serif';
  const MONO = 'ui-monospace,"SF Mono",Menlo,Consolas,monospace';

  const toneColor = (t) => (t === 'good' ? T.up : t === 'bad' ? T.down : t === 'warn' ? T.warn : T.ink2);
  const verdictTone = (v) => {
    if (!v) return 'neutral';
    if (/利多/.test(v)) return 'good';
    if (/利空/.test(v)) return 'bad';
    if (/过热/.test(v)) return 'warn';
    return 'neutral';
  };

  /* --------------------------------------------------------------- 小工具 */
  const raf2 = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

  const loadImg = (url) => new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = rej;
    im.src = url;
  });

  const strip = (s) => String(s || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

  function clone(v) {
    if (Array.isArray(v)) return v.map(clone);
    if (v && typeof v === 'object') {
      const o = {};
      for (const k of Object.keys(v)) o[k] = clone(v[k]);
      return o;
    }
    return v;                       // 函数原样保留（formatter 不能丢）
  }

  /* 把看板尺寸的 option 放大到导出尺寸：字号、线宽、图例尺寸按比例放大，
     grid 重设（导出画布更宽，左侧留白可以大一些）。 */
  function prepOption(opt, scale) {
    const FS = scale || 1.85;
    const LW = 1.45;
    const o = clone(opt);
    delete o.__after;               // 依赖 DOM 覆盖层（牛熊峰谷标注），画不进 canvas
    o.animation = false;

    const walk = (node, parent) => {
      if (!node || typeof node !== 'object') return;
      if (Array.isArray(node)) { node.forEach((n) => walk(n, parent)); return; }
      for (const k of Object.keys(node)) {
        const v = node[k];
        if (typeof v === 'number') {
          if (k === 'fontSize') node[k] = Math.round(v * FS);
          else if (parent === 'lineStyle' && k === 'width') node[k] = Math.max(1, v * LW);
          else if (k === 'symbolSize') node[k] = v * LW;
          else if (k === 'barWidth' && v > 0) node[k] = v * LW;
          else if (k === 'borderWidth') node[k] = Math.max(0, v * LW);
          else if (k === 'itemGap' || k === 'itemWidth' || k === 'itemHeight') node[k] = v * LW;
          else if (k === 'borderRadius') node[k] = v * LW;
          else if (k === 'padding' && parent !== undefined) node[k] = Array.isArray(v) ? v : v * LW;
        } else if (v && typeof v === 'object') {
          walk(v, k);
        }
      }
    };
    walk(o, undefined);

    const top = o.legend ? 104 : 34;
    const grids = Array.isArray(o.grid) ? o.grid : o.grid ? [o.grid] : [];
    grids.forEach((g) => {
      g.left = 24; g.right = 24; g.top = Math.max(g.top || 0, top); g.bottom = 16;
      g.containLabel = true;
    });
    return o;
  }

  /* 在离屏容器里用同一份 option 画一次，取出 PNG */
  async function chartImage(id, w, h) {
    let opt = null;
    try { opt = chartOption(id); } catch (e) { console.error('[export]', id, e); }
    if (!opt) return null;

    /* 类目多的图（矩阵、多资产条形）放大字号会挤爆，按类目数降档 */
    const cats = (opt.xAxis && opt.xAxis.data && opt.xAxis.data.length) || 0;
    const scale = cats > 12 ? 1.35 : 1.85;

    const host = document.createElement('div');
    host.style.cssText = `position:absolute;left:-10000px;top:0;width:${w}px;height:${h}px;`;
    document.body.appendChild(host);
    const chart = echarts.init(host, null, { renderer: 'canvas', width: w, height: h });
    try {
      chart.setOption(prepOption(opt, scale), true);
      await raf2();
      const url = chart.getDataURL({ type: 'png', pixelRatio: 1, backgroundColor: 'rgba(0,0,0,0)' });
      return await loadImg(url);
    } finally {
      chart.dispose();
      host.remove();
    }
  }

  /* --------------------------------------------------------------- 绘图基元 */
  function frame() {
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = T.paper;
    ctx.fillRect(0, 0, W, H);

    const g = ctx.createLinearGradient(0, 0, W, 0);
    g.addColorStop(0, T.gold);
    g.addColorStop(0.5, T.goldBright);
    g.addColorStop(1, T.goldSoft);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, 8);
    ctx.fillRect(0, H - 8, W, 8);
    return { cv, ctx };
  }

  function rule(ctx, y, color) {
    ctx.save();
    ctx.strokeStyle = color || T.line;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD, y + 0.5);
    ctx.lineTo(W - PAD, y + 0.5);
    ctx.stroke();
    ctx.restore();
  }

  function text(ctx, s, x, y, o) {
    const opt = o || {};
    const size = opt.size || 26;
    const weight = opt.weight || 400;
    ctx.save();
    ctx.font = `${weight} ${size}px ${opt.font || SANS}`;
    ctx.fillStyle = opt.color || T.ink;
    ctx.textAlign = opt.align || 'left';
    ctx.textBaseline = 'alphabetic';
    if (opt.ls) { try { ctx.letterSpacing = `${opt.ls}px`; } catch (e) { /* 老浏览器忽略字距 */ } }
    ctx.fillText(s, x, y);
    ctx.restore();
    return ctx.measureText ? 0 : 0;
  }

  function measure(ctx, s, size, weight, font) {
    ctx.save();
    ctx.font = `${weight || 400} ${size}px ${font || SANS}`;
    const w = ctx.measureText(s).width;
    ctx.restore();
    return w;
  }

  /* 中英混排折行：ASCII 串（数字、英文单词）整体不拆 */
  function wrap(ctx, s, maxW, size, weight) {
    ctx.save();
    ctx.font = `${weight || 400} ${size}px ${SANS}`;
    const tokens = String(s || '').match(/[A-Za-z0-9@#.,:%+\-/×·]+|\s+|[\s\S]/g) || [];
    const lines = [];
    let cur = '';
    for (const tk of tokens) {
      if (tk === '\n') { lines.push(cur); cur = ''; continue; }
      const next = cur + tk;
      if (cur && ctx.measureText(next).width > maxW) { lines.push(cur.replace(/\s+$/, '')); cur = tk.replace(/^\s+/, ''); }
      else cur = next;
    }
    if (cur) lines.push(cur.replace(/\s+$/, ''));
    ctx.restore();
    return lines;
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  /* 返回该 chip 的宽度，便于横向排布 */
  function chip(ctx, x, y, label, value, tone, o) {
    const opt = o || {};
    const size = opt.size || 25;
    const h = opt.h || 52;
    const padX = 18;
    const lw = measure(ctx, label, size, 500);
    const vw = value ? measure(ctx, value, size, 700) : 0;
    const w = padX * 2 + lw + (value ? 8 + vw : 0);

    ctx.save();
    ctx.fillStyle = opt.fill || T.card;
    ctx.strokeStyle = T.line;
    ctx.lineWidth = 1;
    roundRect(ctx, x, y, w, h, 10);
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    text(ctx, label, x + padX, y + h / 2 + size * 0.36, { size, weight: 500, color: T.muted });
    if (value) {
      text(ctx, value, x + padX + lw + 8, y + h / 2 + size * 0.36,
        { size, weight: 700, color: opt.valueColor || toneColor(tone) });
    }
    return w;
  }

  function footer(ctx, left, right) {
    rule(ctx, 1360);
    text(ctx, left, PAD, 1396, { size: 20, color: T.muted });
    if (right) text(ctx, right, W - PAD, 1396, { size: 20, color: T.muted, align: 'right' });
  }

  function kicker(ctx, s) {
    text(ctx, s, PAD, 92, { size: 23, weight: 600, color: T.gold, ls: 2.4 });
  }

  /* ----------------------------------------------------------- 元数据整理 */
  const groupOf = (() => {
    const m = new Map();
    (B.sections || []).forEach((s) => {
      (s.cards || []).forEach((c) => m.set(c.id, s.title));
      (s.entries || s.charts || []).forEach((e) => m.set(e.id, s.title));
    });
    (B.chart_order || []).forEach((id) => { if (!m.has(id)) m.set(id, '历史洞察'); });
    return (id) => m.get(id) || '';
  })();

  const digitsFor = (v) => {
    const a = Math.abs(v);
    return a >= 1000 ? 0 : a >= 10 ? 1 : 2;
  };

  /* 数值展示：最多 1~3 位小数并去掉尾随零（4107.4 → 4,107.4，65.0 → 65） */
  function fmtVal(v) {
    if (v === null || v === undefined || !isFinite(v)) return '—';
    const a = Math.abs(v);
    const d = a >= 1000 ? 1 : a >= 10 ? 2 : 3;
    return v.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: d });
  }

  /* 折行 + 超长省略，避免把半句话截在图片边缘 */
  function clipLines(ctx, s, maxW, size, weight, maxLines) {
    const all = wrap(ctx, s, maxW, size, weight);
    if (all.length <= maxLines) return all;
    const out = all.slice(0, maxLines);
    let last = out[maxLines - 1];
    while (last.length > 1 && measure(ctx, last + '…', size, weight) > maxW) last = last.slice(0, -1);
    out[maxLines - 1] = last + '…';
    return out;
  }

  /* 单序列图的分位：最新值在该序列近 N 年观测里的位置（与看板口径一致，只报位置） */
  function pctOf(pts, years) {
    if (!pts || pts.length < 20) return null;
    const lastY = parseInt(String(pts[pts.length - 1][0]).slice(0, 4), 10);
    const win = pts.filter((p) => parseInt(String(p[0]).slice(0, 4), 10) >= lastY - years);
    if (win.length < 12) return null;
    const last = win[win.length - 1][1];
    let below = 0;
    let eq = 0;
    win.forEach((p) => { if (p[1] < last) below += 1; else if (p[1] === last) eq += 1; });
    return Math.round(((below + eq * 0.5) / win.length) * 100);
  }

  function metaOf(id) {
    const card = cardById.get(id);
    if (card) {
      return {
        title: card.name || id,
        group: groupOf(id),
        unit: card.unit || '',
        note: strip(card.note),
        asof: card.date || '',
        value: fmtNum(card.value, fmtDigits(card)),
        chips: (card.changes || [])
          .filter((x) => x.value !== null && x.value !== undefined)
          .map((x) => ({
            label: x.label,
            text: signed(x.value, deltaSuffix(card), deltaDigits(card)),
            tone: x.value > 0 ? 'good' : x.value < 0 ? 'bad' : 'neutral',
          })),
        pct: card.pct && card.pct['10y'] !== null && card.pct['10y'] !== undefined ? card.pct['10y'] : null,
      };
    }
    const ins = B.charts[id] || {};
    const s = (ins.series || [])[0];
    const pts = (s && s.points) || [];
    const last = pts.length ? pts[pts.length - 1] : null;
    return {
      title: ins.title || id,
      group: groupOf(id),
      unit: strip(ins.unit),
      note: strip(ins.note) || strip(ins.extra),
      /* 无序列的图（相关性矩阵、资产回报）时间在 asOf 里，不能只读 series */
      asof: last ? String(last[0]) : strip(ins.asOf),
      value: last ? fmtVal(last[1]) : '',
      chips: [],
      pct: last ? pctOf(pts, 10) : null,
    };
  }

  /* ------------------------------------------------------------- 图卡：内容 */
  async function cardChart(id) {
    const m = metaOf(id);
    const hasValue = !!m.value;
    const chartH = hasValue ? 806 : 900;

    const { cv, ctx } = frame();
    const img = await chartImage(id, INNER, chartH);

    kicker(ctx, (m.group || '黄金研究看板').toUpperCase() + ' · GOLD RESEARCH');
    text(ctx, m.title, PAD, 158, { size: 52, weight: 800 });

    const subBits = [m.unit, m.asof ? `截至 ${m.asof}` : ''].filter(Boolean);
    if (subBits.length) text(ctx, subBits.join(' · '), PAD, 200, { size: 24, color: T.muted });
    rule(ctx, 226);

    const yChart = 250;
    if (img) ctx.drawImage(img, PAD, yChart, INNER, chartH);

    rule(ctx, yChart + chartH + 26);

    let y = yChart + chartH + 26;
    if (hasValue) {
      y += 96;
      text(ctx, m.value, PAD, y, { size: 86, weight: 800 });
      const vw = measure(ctx, m.value, 86, 800);
      if (m.unit) text(ctx, m.unit, PAD + vw + 14, y - 6, { size: 28, color: T.muted });

      /* 右侧变化量 chips（今日/环比/同比…） */
      let cx = W - PAD;
      const chips = m.chips.slice(0, 2).reverse();
      chips.forEach((c) => {
        const w = measure(ctx, c.label, 25, 500) + measure(ctx, c.text, 25, 700) + 44;
        cx -= w;
        chip(ctx, cx, y - 62, c.label, c.text, c.tone, { size: 25, h: 52 });
        cx -= 12;
      });

      y += 46;
      const bits = [];
      if (m.pct !== null && m.pct !== undefined) {
        const tag = m.pct >= 80 ? ' · 历史极值区' : m.pct <= 20 ? ' · 历史低位区' : '';
        bits.push(`近 10 年分位 ${Math.round(m.pct)}%${tag}`);
      }
      bits.push('只描述位置，不给买卖信号');
      text(ctx, bits.join(' · '), PAD, y, { size: 24, color: T.muted });
      y += 34;
    } else {
      y += 44;
      y += 34;
    }

    /* 一句解读：note 整段，最多 2 行，超长加省略号 */
    if (m.note) {
      clipLines(ctx, m.note, INNER, 26, 400, 2)
        .forEach((ln, i) => text(ctx, ln, PAD, y + i * 42, { size: 26, color: T.ink2 }));
    }

    footer(ctx, `数据截至 ${m.asof || '—'}`, '黄金研究看板 · 不预测金价，只帮你看清黄金在反映什么');
    return cv;
  }

  /* ------------------------------------------------------------- 图卡：封面 */
  function cardCover() {
    const { cv, ctx } = frame();
    const g = (B.hero && B.hero.gold) || {};
    const gc = (B.hero && B.hero.gold_cny) || {};

    kicker(ctx, 'GOLD RESEARCH BOARD');
    text(ctx, '黄金研究看板', PAD, 196, { size: 92, weight: 800 });
    text(ctx, '不预测金价，只帮你看清黄金正在反映什么', PAD, 254, { size: 30, color: T.ink2 });
    rule(ctx, 296);

    text(ctx, '国际金价 · COMEX 主力连续', PAD, 358, { size: 25, color: T.muted });
    const val = g.value !== undefined ? fmtVal(g.value) : '—';
    text(ctx, val, PAD, 486, { size: 132, weight: 800 });
    const vw = measure(ctx, val, 132, 800);
    text(ctx, '美元/盎司', PAD + vw + 18, 486, { size: 32, color: T.muted });

    let cx = PAD;
    [['今日', g.chg_1d], ['年初至今', g.chg_ytd], ['近一年', g.chg_1y]].forEach(([lb, v]) => {
      if (v === null || v === undefined) return;
      const txt = signed(v, '%', 2);
      const w = measure(ctx, lb, 25, 500) + measure(ctx, txt, 25, 700) + 44;
      chip(ctx, cx, 520, lb, txt, v > 0 ? 'good' : v < 0 ? 'bad' : 'neutral', { size: 25, h: 52 });
      cx += w + 12;
    });

    /* 近一年迷你走势线（hero.gold.spark，构建期已抽稀到 ~120 点） */
    const pts = (g.spark || []).map((p) => p[1]);
    const sy = 622, sh = 224;
    if (pts.length > 2) {
      const lo = Math.min(...pts);
      const hi = Math.max(...pts);
      const X = (i) => PAD + (i * INNER) / (pts.length - 1);
      const Y = (v) => sy + sh - ((v - lo) / (hi - lo || 1)) * sh;

      const grad = ctx.createLinearGradient(0, sy, 0, sy + sh);
      grad.addColorStop(0, 'rgba(168,137,42,.22)');
      grad.addColorStop(1, 'rgba(168,137,42,0)');
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(X(0), sy + sh);
      pts.forEach((v, i) => ctx.lineTo(X(i), Y(v)));
      ctx.lineTo(X(pts.length - 1), sy + sh);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      pts.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
      ctx.strokeStyle = T.gold;
      ctx.lineWidth = 3;
      ctx.lineJoin = 'round';
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(X(pts.length - 1), Y(pts[pts.length - 1]), 7, 0, Math.PI * 2);
      ctx.fillStyle = T.goldBright;
      ctx.fill();
      ctx.restore();

      text(ctx, `近一年走势 ${g.spark[0][0]} → ${g.spark[g.spark.length - 1][0]}`,
        PAD, sy - 22, { size: 23, color: T.muted });
    }
    rule(ctx, 892);

    /* 人民币金价：境内读者的实际口径 */
    text(ctx, '人民币金价 · 上金所 Au99.99 成交价', PAD, 946, { size: 25, color: T.muted });
    if (gc.value !== undefined) {
      const cv2 = fmtNum(gc.value, 2);
      text(ctx, cv2, PAD, 1030, { size: 66, weight: 800 });
      const w2 = measure(ctx, cv2, 66, 800);
      text(ctx, '元/克', PAD + w2 + 12, 1030, { size: 26, color: T.muted });
      if (gc.chg_1d !== null && gc.chg_1d !== undefined) {
        const txt = signed(gc.chg_1d, '%', 2);
        chip(ctx, PAD + w2 + 76, 986, '今日', txt, gc.chg_1d > 0 ? 'good' : 'bad', { size: 25, h: 52 });
      }
    }
    rule(ctx, 1072);

    /* 三层框架的当下判断：封面就把结论亮出来 */
    text(ctx, '三层框架的当下判断', PAD, 1124, { size: 25, color: T.muted });
    const secs = (B.sections || []).filter((s) => s.state && s.state.verdict);
    let bx = PAD;
    secs.forEach((s) => {
      const tone = verdictTone(s.state.verdict);
      const lb = s.title;
      const w = measure(ctx, lb, 25, 500) + measure(ctx, s.state.verdict, 25, 700) + 44;
      if (bx + w > W - PAD) return;
      chip(ctx, bx, 1156, lb, s.state.verdict, tone, { size: 25, h: 54, valueColor: toneColor(tone) });
      bx += w + 12;
    });

    /* 封面底部不能留空：一句话说清三层框架在干什么 */
    clipLines(ctx, '制度层看债务与货币秩序，宏观层看利率与流动性，市场层看仓位与波动。三层各报位置，不给方向。',
      INNER, 24, 400, 2).forEach((ln, i) => text(ctx, ln, PAD, 1276 + i * 38, { size: 24, color: T.muted }));

    footer(ctx, `30+ 指标 · 1971 年至今 · 数据截至 ${(g.date || '')}`,
      '仅供研究参考，不构成投资建议');
    return cv;
  }

  /* ------------------------------------------------------------- 图卡：结论 */
  function cardVerdict() {
    const { cv, ctx } = frame();
    kicker(ctx, 'FRAMEWORK · 三层框架');
    text(ctx, '现在黄金在反映什么', PAD, 158, { size: 52, weight: 800 });
    text(ctx, '制度层 / 宏观层 / 市场层，每层只报当下位置，不给方向', PAD, 200, { size: 24, color: T.muted });
    rule(ctx, 226);

    const secs = (B.sections || []).filter((s) => s.state && (s.state.points || []).length);
    let y = 282;
    const BLOCK = 254;
    secs.forEach((s, i) => {
      const tone = verdictTone(s.state.verdict);
      const pts = (s.state.points || []).slice(0, 2);

      text(ctx, String(i + 1).padStart(2, '0'), PAD, y + 34, { size: 26, weight: 700, color: T.goldBright });
      text(ctx, s.title, PAD + 52, y + 36, { size: 36, weight: 800 });

      const vtxt = s.state.verdict || '';
      const vw = measure(ctx, vtxt, 25, 700) + 44;
      chip(ctx, W - PAD - vw, y, '', vtxt, tone, { size: 25, h: 50, valueColor: toneColor(tone) });

      /* 每个板块两个关键点，说明只留一行（超长省略）：四个板块必须完整装下 */
      let py = y + 92;
      pts.forEach((p) => {
        text(ctx, p.label, PAD + 52, py, { size: 23, color: T.muted });
        const lw = measure(ctx, p.label, 23, 400);
        text(ctx, String(p.value), PAD + 52 + lw + 16, py - 4,
          { size: 29, weight: 800, color: toneColor(p.tone) });
        const ln = clipLines(ctx, strip(p.text), INNER - 52, 23, 400, 1)[0] || '';
        if (ln) text(ctx, ln, PAD + 52, py + 36, { size: 23, color: T.ink2 });
        py += 74;
      });

      y += BLOCK;
      if (i < secs.length - 1) rule(ctx, y - 22, '#efe8d8');
    });

    /* 页脚用市场数据的日期，不用构建日期：图片发出去时"截至"必须是数据日 */
    footer(ctx, `数据截至 ${(B.hero && B.hero.gold && B.hero.gold.date) || '—'}`,
      '只描述发生了什么 · 不构成投资建议');
    return cv;
  }

  /* ---------------------------------------------------------- 图卡：历史洞察 */
  function cardInsights() {
    const { cv, ctx } = frame();
    const ins = B.insights || {};
    const tone = verdictTone(ins.verdict);

    kicker(ctx, 'INSIGHT · 历史洞察');
    text(ctx, '金价本身的长历史', PAD, 158, { size: 52, weight: 800 });
    text(ctx, strip(ins.subtitle) || '', PAD, 200, { size: 24, color: T.muted });
    rule(ctx, 226);

    text(ctx, '当下判断', PAD, 300, { size: 25, color: T.muted });
    text(ctx, ins.verdict || '—', PAD, 392, { size: 68, weight: 800, color: toneColor(tone) });
    rule(ctx, 440);

    const pts = (ins.points || []).slice(0, 4);
    const cw = (INNER - 24) / 2;
    pts.forEach((p, i) => {
      const x = PAD + (i % 2) * (cw + 24);
      const y = 500 + Math.floor(i / 2) * 250;
      ctx.save();
      ctx.fillStyle = T.card;
      ctx.strokeStyle = T.line;
      ctx.lineWidth = 1;
      roundRect(ctx, x, y, cw, 218, 14);
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      text(ctx, p.label, x + 28, y + 52, { size: 23, color: T.muted });
      text(ctx, String(p.value), x + 28, y + 122, { size: 46, weight: 800, color: toneColor(p.tone) });
      const lines = wrap(ctx, strip(p.text), cw - 56, 22, 400).slice(0, 2);
      lines.forEach((ln, k) => text(ctx, ln, x + 28, y + 168 + k * 30, { size: 22, color: T.ink2 }));
      if (p.date) text(ctx, p.date, x + cw - 28, y + 52, { size: 20, color: T.muted, align: 'right' });
    });

    footer(ctx, `数据截至 ${pts[0] && pts[0].date ? pts[0].date : '—'}`,
      '周期位置与回撤只描述历史，不预测未来');
    return cv;
  }

  /* ------------------------------------------------------------- 图卡：封底 */
  function cardBack() {
    const { cv, ctx } = frame();
    kicker(ctx, 'ABOUT · 数据与口径');
    text(ctx, '数据与口径', PAD, 158, { size: 52, weight: 800 });
    text(ctx, '每个数字都能追到源头，口径写在这里', PAD, 200, { size: 24, color: T.muted });
    rule(ctx, 226);

    text(ctx, '数据来源', PAD, 286, { size: 27, weight: 700 });
    const srcs = (B.sources || []).map(strip).filter(Boolean);
    const colW = (INNER - 32) / 2;
    const half = Math.ceil(srcs.length / 2);
    const colY = [342, 342];            // 每列各走各的游标，行高按实际行数算
    srcs.forEach((s, i) => {
      const col = i < half ? 0 : 1;
      const x = PAD + col * (colW + 32);
      const y = colY[col];
      text(ctx, '·', x, y, { size: 22, color: T.goldBright });
      const lines = clipLines(ctx, s, colW - 20, 21, 400, 3);
      lines.forEach((ln, k) => text(ctx, ln, x + 18, y + k * 29, { size: 21, color: T.ink2 }));
      colY[col] = y + lines.length * 29 + 14;
    });

    let y = Math.max(colY[0], colY[1]) + 24;
    rule(ctx, y);
    y += 52;
    text(ctx, '口径说明', PAD, y, { size: 27, weight: 700 });
    y += 42;
    const notes = [
      '时间轴统一从 1971 年 1 月起（美元与黄金脱钩，此前金本位口径不可比）。',
      '分位数是「最新值在过去 10 年观测中的位置」，只描述位置，不是买卖信号。',
      '人民币金价取上金所 Au99.99 实际成交价；上海金溢价对比按当日汇率折算的伦敦金平价。',
      '日频每交易日更新，周频（COT、H.4.1）每周，月频/季频随发布更新。',
    ];
    notes.forEach((n) => {
      text(ctx, '—', PAD, y, { size: 22, color: T.goldBright });
      const lines = clipLines(ctx, n, INNER - 26, 22, 400, 2);
      lines.forEach((ln, k) => text(ctx, ln, PAD + 26, y + k * 33, { size: 22, color: T.ink2 }));
      y += lines.length * 33 + 12;
    });

    /* 免责声明框 */
    const boxY = y + 16;
    const boxH = 106;
    ctx.save();
    ctx.fillStyle = '#f2ede1';
    ctx.strokeStyle = T.line;
    ctx.lineWidth = 1;
    roundRect(ctx, PAD, boxY, INNER, boxH, 14);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    const dis = '本看板仅供学习和研究参考，不构成任何投资建议。指标与图表只描述「发生了什么」，不提供买卖信号；黄金投资有风险，决策需自行判断。';
    clipLines(ctx, dis, INNER - 56, 22, 400, 2)
      .forEach((ln, i) => text(ctx, ln, PAD + 28, boxY + 44 + i * 32, { size: 22, color: T.ink2 }));

    footer(ctx, `生成于 ${B.generated_at_local || '—'}`, 'github.com/Jst-Well-Dan/gold-dashboard');
    return cv;
  }

  /* --------------------------------------------------------------- 图卡清单 */
  const CURATED = new Set([
    'cover', 'verdict', 'gold_long_log', 'cny_gold', 'shanghai_premium',
    'GFDEGDQ188S', 'USD_RESERVE_SHARE', 'cb_net_quarterly',
    'DFII10', 'DTWEXBGS', 'WALCL',
    'GOLD_COT', 'GVZCLS',
    'gold_drawdown', 'gold_correlation', 'gold_annual',
    'back',
  ]);

  function groups() {
    const gs = [];
    gs.push({
      key: 'frame', label: '封面 / 封底 / 结论',
      items: [
        { id: 'cover', label: '封面（金价 + 三层判断）' },
        { id: 'verdict', label: '三层结论（纯文字）' },
        { id: 'back', label: '封底（数据来源与口径）' },
      ],
    });
    (B.sections || []).forEach((s) => {
      const seen = new Set();
      const items = [];
      (s.cards || []).forEach((c) => {
        if (seen.has(c.id)) return;
        seen.add(c.id);
        items.push({ id: c.id, label: c.name || c.id });
      });
      (s.entries || s.charts || []).forEach((e) => {
        if (seen.has(e.id)) return;
        seen.add(e.id);
        const ins = B.charts[e.id] || {};
        items.push({ id: e.id, label: ins.title || e.id });
      });
      if (items.length) gs.push({ key: s.key, label: s.title, items });
    });
    const covered = new Set();
    gs.forEach((g) => g.items.forEach((it) => covered.add(it.id)));
    const rest = (B.chart_order || [])
      .filter((id) => !covered.has(id))
      .map((id) => ({ id, label: (B.charts[id] && B.charts[id].title) || id }));
    if (rest.length) gs.push({ key: 'insights', label: '历史洞察', items: rest });
    if (B.insights && (B.insights.points || []).length) {
      gs[0].items.push({ id: 'insight-text', label: '历史洞察（纯文字）' });
    }
    return gs;
  }

  const RENDERERS = {
    cover: cardCover,
    verdict: cardVerdict,
    back: cardBack,
    'insight-text': cardInsights,
  };

  const fileName = (i, id) => {
    const m = RENDERERS[id] ? { title: ({ cover: '封面', verdict: '三层结论', back: '数据与口径', 'insight-text': '历史洞察' })[id] } : metaOf(id);
    const safe = String(m.title || id).replace(/[\\/:*?"<>|\s]+/g, '');
    return `${String(i + 1).padStart(2, '0')}-${safe}.png`;
  };

  async function renderCanvas(id) {
    const fn = RENDERERS[id];
    return fn ? await fn() : await cardChart(id);
  }

  async function renderOne(id) {
    return (await renderCanvas(id)).toDataURL('image/png');
  }

  /* 预览网格只需要能看清，不需要 1080×1440：不缩一下，17 张 × 300 KB 的
     dataURL 会堆成 5 MB 的 DOM，滚动和截图都会卡。ZIP 里仍用原图。 */
  function downscale(cv, w) {
    const h = Math.round((w * cv.height) / cv.width);
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const x = c.getContext('2d');
    x.imageSmoothingEnabled = true;
    x.imageSmoothingQuality = 'high';
    x.drawImage(cv, 0, 0, w, h);
    return c;
  }

  /* ------------------------------------------------------------------- ZIP */
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let i = 0; i < 256; i += 1) {
      let c = i;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[i] = c >>> 0;
    }
    return t;
  })();

  function crc32(u8) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < u8.length; i += 1) c = CRC_TABLE[(c ^ u8[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  const bytesOfDataUrl = (url) => {
    const b = atob(url.split(',')[1]);
    const u = new Uint8Array(b.length);
    for (let i = 0; i < b.length; i += 1) u[i] = b.charCodeAt(i);
    return u;
  };

  /* store-only ZIP：PNG 已经压过，再 deflate 只是白费 CPU */
  function buildZip(files) {
    const enc = new TextEncoder();
    const parts = [];
    const central = [];
    let offset = 0;
    const now = new Date();
    const dtime = ((now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1)) & 0xFFFF;
    const ddate = (((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate()) & 0xFFFF;

    files.forEach((f) => {
      const name = enc.encode(f.name);
      const crc = crc32(f.data);
      const size = f.data.length;

      const lh = new Uint8Array(30 + name.length);
      const dv = new DataView(lh.buffer);
      dv.setUint32(0, 0x04034b50, true);
      dv.setUint16(4, 20, true);
      dv.setUint16(6, 0x0800, true);       // UTF-8 文件名
      dv.setUint16(8, 0, true);
      dv.setUint16(10, dtime, true);
      dv.setUint16(12, ddate, true);
      dv.setUint32(14, crc, true);
      dv.setUint32(18, size, true);
      dv.setUint32(22, size, true);
      dv.setUint16(26, name.length, true);
      dv.setUint16(28, 0, true);
      lh.set(name, 30);
      parts.push(lh, f.data);

      const ch = new Uint8Array(46 + name.length);
      const cv = new DataView(ch.buffer);
      cv.setUint32(0, 0x02014b50, true);
      cv.setUint16(4, 20, true);
      cv.setUint16(6, 20, true);
      cv.setUint16(8, 0x0800, true);
      cv.setUint16(10, 0, true);
      cv.setUint16(12, dtime, true);
      cv.setUint16(14, ddate, true);
      cv.setUint32(16, crc, true);
      cv.setUint32(20, size, true);
      cv.setUint32(24, size, true);
      cv.setUint16(28, name.length, true);
      cv.setUint32(42, offset, true);
      ch.set(name, 46);
      central.push(ch);

      offset += lh.length + size;
    });

    const cdSize = central.reduce((a, c) => a + c.length, 0);
    const eocd = new Uint8Array(22);
    const ev = new DataView(eocd.buffer);
    ev.setUint32(0, 0x06054b50, true);
    ev.setUint16(8, files.length, true);
    ev.setUint16(10, files.length, true);
    ev.setUint32(12, cdSize, true);
    ev.setUint32(16, offset, true);

    return new Blob([...parts, ...central, eocd], { type: 'application/zip' });
  }

  function save(blob, name) {
    const a = document.createElement('a');
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  /* -------------------------------------------------------------------- UI */
  const state = { picked: new Set(CURATED), out: [], busy: false };

  function ensureUI() {
    if (document.getElementById('xp-mask')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'xp-open';
    btn.textContent = '导出图片';
    const stamp = document.getElementById('nav-stamp');
    if (stamp && stamp.parentNode) stamp.parentNode.insertBefore(btn, stamp);
    else document.querySelector('.nav .wrap')?.appendChild(btn);

    const mask = document.createElement('div');
    mask.id = 'xp-mask';
    mask.className = 'xp-mask';
    mask.innerHTML = `
      <div class="xp-panel" role="dialog" aria-modal="true" aria-label="导出小红书图卡">
        <header class="xp-head">
          <div>
            <h2>导出小红书图卡</h2>
            <p>1080 × 1440（3:4）· 浅色纸面 · 单篇上限 18 张 · 图与看板同一份数据</p>
          </div>
          <button type="button" class="xp-x" data-xp="close" aria-label="关闭">✕</button>
        </header>
        <div class="xp-body">
          <div class="xp-list" id="xp-list"></div>
          <div class="xp-preview" id="xp-preview">
            <p class="xp-hint">左侧勾选要发的图卡，点「生成预览」。
              每张都会按 3:4 重排：标题、数值、分位、一句解读，图和看板完全一致。</p>
          </div>
        </div>
        <footer class="xp-foot">
          <span class="xp-count" id="xp-count"></span>
          <button type="button" data-xp="curated">恢复精选</button>
          <button type="button" data-xp="none">全不选</button>
          <button type="button" class="xp-primary" data-xp="gen">生成预览</button>
          <button type="button" class="xp-primary" data-xp="zip" disabled>打包下载 ZIP</button>
        </footer>
      </div>`;
    document.body.appendChild(mask);

    const list = mask.querySelector('#xp-list');
    groups().forEach((g) => {
      const box = document.createElement('section');
      box.className = 'xp-group';
      box.innerHTML = `<h3>${g.label}</h3>`;
      g.items.forEach((it) => {
        const lab = document.createElement('label');
        lab.className = 'xp-item';
        const on = state.picked.has(it.id);
        lab.innerHTML = `<input type="checkbox" value="${it.id}"${on ? ' checked' : ''}><span>${it.label}</span>`;
        box.appendChild(lab);
      });
      list.appendChild(box);
    });

    list.addEventListener('change', (e) => {
      const cb = e.target;
      if (!cb || cb.type !== 'checkbox') return;
      if (cb.checked) state.picked.add(cb.value);
      else state.picked.delete(cb.value);
      syncCount();
    });

    mask.addEventListener('click', (e) => {
      const act = e.target.closest('[data-xp]');
      if (!act) {
        if (e.target === mask) close();
        return;
      }
      const a = act.dataset.xp;
      if (a === 'close') close();
      else if (a === 'curated') { state.picked = new Set(CURATED); syncBoxes(); }
      else if (a === 'none') { state.picked.clear(); syncBoxes(); }
      else if (a === 'gen') generate();
      else if (a === 'zip') downloadZip();
      else if (a === 'save') saveOne(Number(act.dataset.i));
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && mask.classList.contains('on')) close();
    });

    btn.addEventListener('click', open);
    syncCount();
  }

  function syncBoxes() {
    document.querySelectorAll('#xp-list input[type="checkbox"]').forEach((cb) => {
      cb.checked = state.picked.has(cb.value);
    });
    syncCount();
  }

  function syncCount() {
    const n = state.picked.size;
    const el = document.getElementById('xp-count');
    if (el) {
      el.textContent = `已选 ${n} 张${n > MAXPICK ? ` · 超出小红书 ${MAXPICK} 张上限` : ''}`;
      el.classList.toggle('over', n > MAXPICK);
    }
    const gen = document.querySelector('[data-xp="gen"]');
    if (gen) gen.disabled = n === 0 || state.busy;
  }

  function open() {
    ensureUI();
    document.getElementById('xp-mask').classList.add('on');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    document.getElementById('xp-mask').classList.remove('on');
    document.body.style.overflow = '';
  }

  const order = () => {
    const ids = [];
    groups().forEach((g) => g.items.forEach((it) => { if (state.picked.has(it.id)) ids.push(it.id); }));
    /* 封底永远排最后：它是收尾，不能夹在图中间 */
    const bi = ids.indexOf('back');
    if (bi >= 0 && bi !== ids.length - 1) { ids.splice(bi, 1); ids.push('back'); }
    return ids;
  };

  async function generate() {
    if (state.busy) return;
    const ids = order();
    if (!ids.length) return;
    state.busy = true;
    syncCount();

    const box = document.getElementById('xp-preview');
    const gen = document.querySelector('[data-xp="gen"]');
    const zip = document.querySelector('[data-xp="zip"]');
    box.innerHTML = '';
    state.out = [];
    if (zip) zip.disabled = true;

    for (let i = 0; i < ids.length; i += 1) {
      const id = ids[i];
      const name = fileName(i, id);
      if (gen) gen.textContent = `生成中 ${i + 1}/${ids.length}`;
      try {
        const cv = await renderCanvas(id);
        const full = cv.toDataURL('image/png');
        const thumb = downscale(cv, 400).toDataURL('image/jpeg', 0.82);
        state.out.push({ name, data: bytesOfDataUrl(full), url: full });
        const fig = document.createElement('figure');
        fig.innerHTML = `<img alt="${name}" src="${thumb}">
          <figcaption><b>${name}</b><button type="button" data-xp="save" data-i="${i}">保存</button></figcaption>`;
        box.appendChild(fig);
      } catch (e) {
        console.error('[export]', id, e);
        const p = document.createElement('p');
        p.className = 'xp-err';
        p.textContent = `第 ${i + 1} 张（${id}）生成失败：${e && e.message ? e.message : e}`;
        box.appendChild(p);
      }
      await raf2();
    }

    if (gen) { gen.textContent = '重新生成'; gen.disabled = false; }
    if (zip) zip.disabled = state.out.length === 0;
    state.busy = false;
    syncCount();
  }

  function saveOne(i) {
    const f = state.out[i];
    if (!f) return;
    save(new Blob([f.data], { type: 'image/png' }), f.name);
  }

  function downloadZip() {
    if (!state.out.length) return;
    const d = new Date();
    const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
    save(buildZip(state.out), `gold-board-xhs-${stamp}.zip`);
  }

  /* ------------------------------------------------------------------ 启动 */
  function init() {
    ensureUI();
    window.__BOARD_EXPORT__ = { open, generate, order, renderOne };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
