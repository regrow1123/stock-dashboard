// Stock-dashboard frontend controller.
// Routes based on <body data-page="…">. Shared Alpine stores and utilities.

(() => {
  'use strict';

  // ---------- utilities ----------

  const narrow = window.matchMedia('(max-width: 640px)');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  const cssVar = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const colorOf = (name, fallback = '') => cssVar(name) || fallback;

  const fmtMoney = (n, cur, { fraction = 0 } = {}) =>
    new Intl.NumberFormat('ko-KR', {
      style: 'currency', currency: cur, maximumFractionDigits: fraction,
    }).format(n);

  const signedMoney = (n, cur, { fraction = 0 } = {}) =>
    new Intl.NumberFormat('ko-KR', {
      style: 'currency', currency: cur, signDisplay: 'always', maximumFractionDigits: fraction,
    }).format(n);

  const pctStr = (n) => (n >= 0 ? '+' : '') + (n * 100).toFixed(2) + '%';
  const pctInt = (n) => (n * 100).toFixed(1) + '%';

  const monthLabel = (iso) => {
    // iso = 'YYYY-MM-DD' -> '4월' (1Y range)
    const [, m] = iso.split('-');
    return `${parseInt(m, 10)}월`;
  };
  const shortDate = (iso) => iso.slice(2, 7); // 'YY-MM'

  const timeLabel = (date = new Date()) =>
    date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });

  async function getJSON(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }

  function hexToRgba(hex, alpha = 1) {
    const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
    if (!m) return `rgba(37, 99, 235, ${alpha})`;
    let h = m[1];
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 0xff}, ${(n >> 8) & 0xff}, ${n & 0xff}, ${alpha})`;
  }

  // Chart.js plugin: draws an idle marker at the last portfolio point and
  // a vertical crosshair when a tooltip is active.
  const chartOrnamentsPlugin = {
    id: 'ornaments',
    afterDatasetsDraw(chart) {
      const { ctx, chartArea, scales, tooltip } = chart;
      const ds = chart.data.datasets[0];
      if (!ds || !ds.data || !ds.data.length) return;

      const markerColor = colorOf('--chart-marker', '#1c1917');
      const axisColor   = colorOf('--chart-axis', '#a8a29e');

      const isHovering = tooltip && tooltip.opacity !== 0 && tooltip.dataPoints?.length;

      if (isHovering) {
        const x = tooltip.caretX;
        ctx.save();
        ctx.strokeStyle = axisColor;
        ctx.lineWidth = 0.5;
        ctx.setLineDash([2, 2]);
        ctx.beginPath();
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.stroke();
        ctx.setLineDash([]);

        // dots at the two intersected datasets
        tooltip.dataPoints.forEach((dp, i) => {
          const isPort = dp.datasetIndex === 0;
          ctx.beginPath();
          ctx.arc(dp.element.x, dp.element.y, isPort ? 3.5 : 2.5, 0, Math.PI * 2);
          ctx.fillStyle = isPort ? markerColor : axisColor;
          ctx.strokeStyle = colorOf('--chart-card-bg', '#ffffff');
          ctx.lineWidth = isPort ? 1.5 : 1;
          ctx.fill();
          ctx.stroke();
        });
        ctx.restore();
        return;
      }

      // idle: small dot at last non-null portfolio point
      let lastIdx = -1;
      for (let i = ds.data.length - 1; i >= 0; i--) {
        if (ds.data[i] != null) { lastIdx = i; break; }
      }
      if (lastIdx < 0) return;
      const x = scales.x.getPixelForValue(lastIdx);
      const y = scales.y.getPixelForValue(ds.data[lastIdx]);
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = markerColor;
      ctx.fill();
      ctx.restore();
    },
  };

  // ---------- Alpine wiring ----------

  document.addEventListener('alpine:init', () => {
    const Alpine = window.Alpine;

    Alpine.store('toast', {
      items: [],
      _id: 0,
      push(msg, kind = 'info', ttl = 3500) {
        const id = ++this._id;
        this.items.push({ id, msg, kind });
        setTimeout(() => {
          this.items = this.items.filter((t) => t.id !== id);
        }, ttl);
      },
    });

    Alpine.data('appShell', () => ({
      scrolled: false,
      refreshing: false,
      _onScroll: null,
      init() {
        this._onScroll = () => { this.scrolled = window.scrollY > 8; };
        window.addEventListener('scroll', this._onScroll, { passive: true });
        this._onScroll();
      },
      destroy() {
        window.removeEventListener('scroll', this._onScroll);
      },
      async refreshNow() {
        if (this.refreshing) return;
        this.refreshing = true;
        try {
          if (typeof window.pageReload === 'function') await window.pageReload();
        } catch (e) {
          console.error(e);
          Alpine.store('toast').push('새로고침 실패', 'error');
        } finally {
          this.refreshing = false;
        }
      },
    }));
  });

  // ---------- helpers ----------

  function escapeHTML(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
  }

  // External Chart.js tooltip — renders into a single .chart-tooltip DOM
  // element appended once into the .chart-canvas-wrap container.
  function externalTooltip(context) {
    const { chart, tooltip } = context;
    const wrap = chart.canvas.parentNode;
    if (!wrap) return;
    let el = wrap.querySelector('.chart-tooltip');
    if (!el) {
      el = document.createElement('div');
      el.className = 'chart-tooltip';
      wrap.appendChild(el);
    }
    if (tooltip.opacity === 0) {
      el.classList.remove('is-visible');
      return;
    }
    const dp = tooltip.dataPoints || [];
    if (!dp.length) return;
    const date = tooltip.title?.[0] || '';
    // both datasets are TWR-rebased to 1.0
    const rows = dp.map((p) => {
      const delta = p.parsed.y - 1;
      const sign = delta >= 0 ? '+' : '';
      const cls = delta >= 0 ? 'pos' : 'neg';
      const key = p.datasetIndex === 0 ? 'PORT' : 'BMK';
      return `<div class="tt-row">
      <span class="tt-key">${key}</span>
      <span class="tt-val ${cls}">${sign}${(delta * 100).toFixed(2)}%</span>
    </div>`;
    }).join('');
    el.innerHTML = `<div class="tt-date">${date}</div>${rows}`;

    const left = tooltip.caretX;
    const top = tooltip.caretY;
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    el.classList.add('is-visible');
  }

  // ---------- Chart.js defaults ----------

  function applyChartDefaults() {
    if (!window.Chart) return;
    const Chart = window.Chart;
    Chart.defaults.font.family = cssVar('--font-sans') || 'system-ui';
    Chart.defaults.color = colorOf('--color-muted', '#6b7280');
    Chart.defaults.borderColor = colorOf('--color-border', '#e5e7eb');
    Chart.defaults.animation = reducedMotion.matches ? false : { duration: 220 };
  }

  // react to OS color scheme changes by redrawing charts
  const darkMq = window.matchMedia('(prefers-color-scheme: dark)');
  const chartRegistry = new Set();
  const redrawCharts = () => {
    applyChartDefaults();
    chartRegistry.forEach((c) => c.update('none'));
  };
  darkMq.addEventListener?.('change', redrawCharts);
  reducedMotion.addEventListener?.('change', redrawCharts);

  // ---------- Overview ----------

  async function renderOverview() {
    applyChartDefaults();
    const [s] = await Promise.all([
      getJSON('/api/summary'),
      renderMarketTicker(),
      renderSentiment(),
    ]);

    renderAccountsList(s.accounts || []);

    const now = timeLabel();
    const u = document.getElementById('last-updated');
    if (u) u.textContent = `${now} 갱신`;
  }

  function fgRatingKo(rating) {
    return {
      'extreme fear': '극단적 공포',
      'fear': '공포',
      'neutral': '중립',
      'greed': '탐욕',
      'extreme greed': '극단적 탐욕',
    }[rating?.toLowerCase()] || rating || '';
  }

  async function renderSentiment() {
    const host = document.getElementById('sentiment');
    if (!host) return;
    let data;
    try {
      data = await getJSON('/api/sentiment');
    } catch (e) {
      host.innerHTML = '';
      return;
    }
    const fg = data.fear_and_greed;
    if (!fg || fg.score == null) {
      host.innerHTML = '';
      return;
    }
    const score = Math.round(fg.score);
    const prev = fg.previous_close != null ? Math.round(fg.previous_close) : null;
    const w = fg.previous_1_week != null ? Math.round(fg.previous_1_week) : null;
    const m = fg.previous_1_month != null ? Math.round(fg.previous_1_month) : null;
    const rating = fgRatingKo(fg.rating);
    host.innerHTML = `
      <div class="sent-card">
        <div class="sent-head">
          <span class="sent-lbl">CNN Fear &amp; Greed</span>
          <span class="sent-score">${score}<span class="sent-rating"> · ${escapeHTML(rating)}</span></span>
        </div>
        <div class="sent-gauge" aria-label="${score} / 100">
          <div class="sent-track"></div>
          ${prev != null ? `<div class="sent-prev" style="left:${prev}%" title="어제 ${prev}"></div>` : ''}
          <div class="sent-marker" style="left:${score}%"></div>
        </div>
        <div class="sent-meta">
          <span>어제 ${prev ?? '—'}</span>
          <span>1주 ${w ?? '—'}</span>
          <span>1달 ${m ?? '—'}</span>
        </div>
      </div>
    `;
  }

  async function renderMarketTicker() {
    const host = document.querySelector('#market-ticker .market-ticker-inner');
    if (!host) return;
    try {
      const rows = await getJSON('/api/markets');
      const itemHtml = (r) => {
        if (r.change_pct == null) {
          return `<span class="mt-item"><span class="mt-lbl">${escapeHTML(r.label)}</span><span class="mt-val muted">—</span></span>`;
        }
        const cls = r.change_pct >= 0 ? 'pos' : 'neg';
        const arrow = r.change_pct >= 0 ? '▲' : '▼';
        const pct = (Math.abs(r.change_pct) * 100).toFixed(2);
        return `<span class="mt-item"><span class="mt-lbl">${escapeHTML(r.label)}</span><span class="mt-val ${cls}">${arrow} ${pct}%</span></span>`;
      };
      const groups = ['kr', 'us', 'alt'];
      host.innerHTML = groups.map((g) => {
        const items = rows.filter((r) => r.group === g).map(itemHtml).join('');
        return items ? `<div class="mt-row">${items}</div>` : '';
      }).join('');
    } catch (e) {
      host.innerHTML = '';
    }
  }

  function renderAccountsList(accounts) {
    const el = document.getElementById('accounts');
    if (!el) return;
    el.setAttribute('aria-busy', 'false');
    if (!accounts.length) {
      el.innerHTML = `<li class="row-item"><div><div class="row-title">계좌가 없습니다</div><div class="row-sub">seed/initial_holdings.yaml 을 확인하세요.</div></div></li>`;
      return;
    }
    el.innerHTML = accounts.map((a) => {
      const dc = a.day_change_pct;
      const dcPill = dc == null ? 'pill-muted' : dc >= 0 ? 'pill-pos' : 'pill-neg';
      const dcText = dc == null ? '—' : pctStr(dc);
      return `
        <li>
          <a class="row-item card-tap" href="/accounts/${a.account_id}"
             aria-label="${escapeHTML(a.name)} 상세 보기, 오늘 ${dcText}">
            <div>
              <div class="row-title">${escapeHTML(a.name)}
                <span class="tag">${escapeHTML(a.broker)}</span>
              </div>
              <div class="row-sub">${a.currency}</div>
            </div>
            <div class="row-right">
              <span class="pill ${dcPill}">${dcText}</span>
            </div>
          </a>
        </li>`;
    }).join('');
  }

  // ---------- Account detail ----------

  let histChart = null;
  let currentRange = '1Y';
  let historyReqSeq = 0;
  let rangeTabsWired = false;

  const RANGE_DAYS = { '1M': 31, '3M': 93, '6M': 186, '1Y': 366 };

  async function renderAccount() {
    applyChartDefaults();
    await Promise.all([
      renderAccountHero(),
      renderAccountWeights(),
      renderAccountHoldings(),
      renderAccountTrades(),
      renderAccountHistory(currentRange),
    ]);
    wireRangeTabs();
  }

  async function renderAccountHero() {
    const hero = document.getElementById('hero');
    const s = await getJSON('/api/summary');
    const row = (s.accounts || []).find((a) => a.account_id === window.ACCOUNT_ID);
    hero.setAttribute('aria-busy', 'false');
    if (!row) {
      hero.innerHTML = `<div class="label">데이터 없음</div>`;
      return;
    }
    const cur = row.currency;
    const pillCls = row.pct_return >= 0 ? 'pill-pos' : 'pill-neg';
    hero.innerHTML = `
      <div class="flex items-baseline justify-between gap-3">
        <span class="label">평가</span>
        <span class="pill ${pillCls}">${pctStr(row.pct_return)}</span>
      </div>
      <div class="hero-number mt-1">${fmtMoney(row.value, cur)}</div>
      <div class="kv mt-3"><span>원가</span><strong>${fmtMoney(row.cost, cur)}</strong></div>
      <div class="kv mt-1"><span>평가손익</span>
        <strong class="${row.pnl >= 0 ? 'pos' : 'neg'}">${signedMoney(row.pnl, cur)}</strong>
      </div>`;
  }

  async function renderAccountWeights() {
    const rows = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/weights`);
    const wrap = document.getElementById('weights');
    wrap.setAttribute('aria-busy', 'false');
    if (!rows.length) {
      wrap.innerHTML = `<div class="row-sub">보유 종목 없음</div>`;
      return;
    }
    const top = [...rows].sort((a, b) => b.weight - a.weight).slice(0, 10);
    wrap.innerHTML = top.map((r) => {
      const wc = r.weight_change; // fraction in pp (e.g., 0.012 = +1.2pp)
      const wcCls = wc == null ? 'muted' : wc >= 0 ? 'pos' : 'neg';
      // negligible movement (< 0.05pp) → "—" so noise is hushed
      const wcText = wc == null
        ? '—'
        : Math.abs(wc) < 0.00005
          ? '—'
          : `${wc >= 0 ? '+' : ''}${(wc * 100).toFixed(2)}%p`;
      const aria = `${escapeHTML(r.name || r.ticker)} ${pctInt(r.weight)} 비중변화 ${wcText}`;
      return `
      <div class="weight-row" aria-label="${aria}">
        <span class="label-txt">
          ${escapeHTML(r.name || r.ticker)}
          <span class="day-change ${wcCls}">${wcText}</span>
        </span>
        <span class="pct">${pctInt(r.weight)}</span>
        <div class="weight-bar" aria-hidden="true">
          <span style="width: ${(r.weight * 100).toFixed(1)}%"></span>
        </div>
      </div>`;
    }).join('');
  }

  async function renderAccountHoldings() {
    const rows = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/holdings`);
    const total = rows.reduce((s, r) => s + r.value, 0);
    const cur = window.ACCOUNT_CURRENCY;

    const list = document.getElementById('holdings-list');
    list.setAttribute('aria-busy', 'false');
    if (!rows.length) {
      list.innerHTML = `<li class="row-item"><div><div class="row-title">보유 종목이 없습니다</div></div></li>`;
    } else {
      list.innerHTML = rows.map((r) => {
        const dc = r.day_change_pct;
        const dcPill = dc == null ? 'pill-muted' : dc >= 0 ? 'pill-pos' : 'pill-neg';
        const dcText = dc == null ? '—' : pctStr(dc);
        return `
          <li>
            <div class="row-item">
              <div>
                <div class="row-title">${escapeHTML(r.name || r.ticker)}</div>
                <div class="row-sub">${escapeHTML(r.ticker)} · ${r.quantity}주 · 평단 ${fmtMoney(r.avg_price, cur, { fraction: 2 })}</div>
              </div>
              <div class="row-right">
                ${fmtMoney(r.value, cur)}
                <div class="row-sub">
                  <span class="pill ${dcPill}">${dcText}</span>
                </div>
              </div>
            </div>
          </li>`;
      }).join('');
    }

    const tbody = document.querySelector('#holdings-table tbody');
    if (tbody) {
      tbody.innerHTML = rows.map((r) => {
        const weight = total > 0 ? r.value / total : 0;
        const dc = r.day_change_pct;
        const dcPill = dc == null ? 'pill-muted' : dc >= 0 ? 'pill-pos' : 'pill-neg';
        const dcText = dc == null ? '—' : pctStr(dc);
        return `
          <tr>
            <td>
              ${escapeHTML(r.name || r.ticker)}
              <div class="row-sub">${escapeHTML(r.ticker)}</div>
            </td>
            <td>${r.quantity}</td>
            <td>${fmtMoney(r.avg_price, cur, { fraction: 2 })}</td>
            <td>${r.current_price != null ? fmtMoney(r.current_price, cur, { fraction: 2 }) : '—'}</td>
            <td>${fmtMoney(r.value, cur)}</td>
            <td>${pctInt(weight)}</td>
            <td><span class="pill ${dcPill}">${dcText}</span></td>
          </tr>`;
      }).join('');
    }
  }

  async function renderAccountTrades() {
    const rows = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/trades?limit=20`);
    const cur = window.ACCOUNT_CURRENCY;

    const list = document.getElementById('trades-list');
    list.setAttribute('aria-busy', 'false');
    if (!rows.length) {
      list.innerHTML = `<li class="row-item"><div><div class="row-title">거래 내역이 없습니다</div></div></li>`;
    } else {
      list.innerHTML = rows.map((t) => {
        const pill = t.side === 'buy' ? 'pill-pos' : 'pill-neg';
        return `
          <li>
            <div class="row-item">
              <div>
                <div class="row-title">${escapeHTML(t.name || t.ticker)}</div>
                <div class="row-sub">
                  <time datetime="${t.executed_at}">${t.executed_at}</time>
                  · <span class="pill ${pill}">${t.side}</span>
                  · ${t.quantity}주
                </div>
              </div>
              <div class="row-right">${fmtMoney(t.price, cur, { fraction: 2 })}</div>
            </div>
          </li>`;
      }).join('');
    }

    const tbody = document.querySelector('#trades-table tbody');
    if (tbody) {
      tbody.innerHTML = rows.map((t) => `
        <tr>
          <td><time datetime="${t.executed_at}">${t.executed_at}</time></td>
          <td>${escapeHTML(t.name || t.ticker)}<div class="row-sub">${escapeHTML(t.ticker)}</div></td>
          <td><span class="pill ${t.side === 'buy' ? 'pill-pos' : 'pill-neg'}">${t.side}</span></td>
          <td>${t.quantity}</td>
          <td>${fmtMoney(t.price, cur, { fraction: 2 })}</td>
        </tr>`).join('');
    }
  }

  function wireRangeTabs() {
    if (rangeTabsWired) return;
    const tabs = document.getElementById('range-tabs');
    if (!tabs) return;
    tabs.addEventListener('click', (e) => {
      const btn = e.target.closest('.chip');
      if (!btn || !tabs.contains(btn)) return;
      const r = btn.dataset.range;
      if (!r || r === currentRange) return;
      currentRange = r;
      tabs.querySelectorAll('.chip').forEach((b) => {
        b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
      });
      renderAccountHistory(currentRange);
    });
    rangeTabsWired = true;
  }

  async function renderAccountHistory(range) {
    const seq = ++historyReqSeq;
    const days = RANGE_DAYS[range] || 366;
    const from = new Date(Date.now() - days * 86400 * 1000).toISOString().slice(0, 10);
    const wrap = document.getElementById('history-wrap');
    const titleEl = document.getElementById('history-title');
    const heroEl = document.getElementById('history-hero');
    const benchStatEl = document.getElementById('history-bench-stat');
    wrap.setAttribute('aria-busy', 'true');

    let bench;
    try {
      bench = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/benchmark?from=${from}`);
    } catch (e) {
      if (seq !== historyReqSeq) return; // a newer request superseded us
      wrap.setAttribute('aria-busy', 'false');
      document.getElementById('history-summary').textContent = '자산 추이를 불러오지 못했습니다.';
      window.Alpine?.store('toast')?.push('차트 데이터를 불러오지 못했습니다', 'error');
      return;
    }
    if (seq !== historyReqSeq) return; // stale result from an older tab click

    const portEndVal = bench.portfolio[bench.portfolio.length - 1]?.value;
    const benchEndVal = bench.benchmark[bench.benchmark.length - 1]?.value;
    const portReturn = portEndVal != null ? portEndVal - 1 : null;
    const benchReturn = benchEndVal != null ? benchEndVal - 1 : null;
    const benchName = bench.benchmark_name || bench.benchmark_ticker || '벤치마크';

    // y-axis bounds: snap to nice step intervals so horizontal gridlines
    // land at clean %-values (e.g. 0/25/50/75 instead of jagged auto-picks)
    // and tight-fit so we don't waste the canvas on Chart.js's default
    // -100%..+200% rounding when one series is far above 1.0.
    const allValues = [
      ...bench.portfolio.map((p) => p.value),
      ...bench.benchmark.map((p) => p.value),
    ].filter((v) => v != null);
    const dataMin = allValues.length ? Math.min(1, ...allValues) : 0.95;
    const dataMax = allValues.length ? Math.max(1, ...allValues) : 1.05;
    // 4 evenly-spaced gridlines whose labels are all multiples of 10%.
    // yMin snaps DOWN to a 10%-grid line; step is the smallest 10%-multiple
    // that lets 3 intervals cover the data; yMax = yMin + 3*step.
    const yMin = Math.floor(dataMin * 10) / 10;
    const yStep = Math.max(0.1, Math.ceil((dataMax - yMin) / 3 * 10) / 10);
    const yMax = yMin + 3 * yStep;

    if (titleEl) titleEl.textContent = `자산 추이 · vs ${benchName}`;
    if (heroEl) {
      if (portReturn != null) {
        heroEl.textContent = pctStr(portReturn);
        heroEl.className = `chart-hero ${portReturn >= 0 ? 'pos' : 'neg'}`;
      } else {
        heroEl.textContent = '—';
        heroEl.className = 'chart-hero';
      }
    }
    if (benchStatEl) {
      benchStatEl.textContent = benchReturn != null
        ? `${benchName} ${pctStr(benchReturn)}`
        : `${benchName} —`;
    }

    const allDates = Array.from(new Set([
      ...bench.portfolio.map((p) => p.date),
      ...bench.benchmark.map((p) => p.date),
    ])).sort();
    const portMap = Object.fromEntries(bench.portfolio.map((p) => [p.date, p.value]));
    const benchMap = Object.fromEntries(bench.benchmark.map((p) => [p.date, p.value]));

    const canvas = document.getElementById('history');
    // Chart.js throws if the canvas is already owned by a live chart — always
    // look up the live instance directly rather than trusting a stale `histChart` var.
    const existing = window.Chart?.getChart?.(canvas);
    if (existing) { existing.destroy(); chartRegistry.delete(existing); }
    // clear any stale external-tooltip from the previous chart instance
    canvas.parentNode?.querySelector('.chart-tooltip')?.classList.remove('is-visible');
    const ctx = canvas.getContext('2d');

    const lineColor      = colorOf('--chart-line', '#1c1917');
    const lineBenchColor = colorOf('--chart-line-bench', '#a8a29e');

    const portWidth  = 1.5;
    const benchWidth = 1;

    histChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: allDates,
        datasets: [
          {
            label: '포트폴리오',
            data: allDates.map((d) => portMap[d] ?? null),
            spanGaps: true,
            borderColor: lineColor,
            fill: false,
            pointRadius: 0,
            pointHoverRadius: 0,
            borderWidth: portWidth,
            tension: 0.18,
          },
          {
            label: benchName,
            data: allDates.map((d) => benchMap[d] ?? null),
            spanGaps: true,
            borderColor: lineBenchColor,
            borderDash: [2, 3],
            pointRadius: 0,
            pointHoverRadius: 0,
            borderWidth: benchWidth,
            tension: 0.18,
            fill: false,
          },
        ],
      },
      plugins: [chartOrnamentsPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: narrow.matches ? 1.3 : 2.4,
        interaction: { intersect: false, mode: 'index' },
        animation: reducedMotion.matches ? false : { duration: 220 },
        // color-property animations interpolate strings → can't handle CanvasGradient
        // returned by the scriptable portFill; disable to avoid tick crashes.
        animations: { colors: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: false,
            external: externalTooltip,
            mode: 'index',
            intersect: false,
          },
        },
        scales: {
          x: { display: false },
          // single y-axis, TWR rebased to 1.0. Labels rendered as ±% so
          // the reader can gauge absolute performance without a baseline.
          y: {
            display: true,
            position: 'right',
            min: yMin,
            max: yMax,
            border: { display: false },
            grid: {
              // 0%-baseline (TWR = 1.0) gets a slightly stronger line so the
              // reader can quickly see gain/loss without reading the labels.
              color: (ctx) => (ctx.tick && Math.abs(ctx.tick.value - 1) < 0.005
                ? colorOf('--chart-card-border', '#e8e6df')
                : colorOf('--chart-grid', '#e8e6df')),
              lineWidth: (ctx) => (ctx.tick && Math.abs(ctx.tick.value - 1) < 0.005 ? 1 : 0.5),
              drawTicks: false,
            },
            ticks: {
              color: colorOf('--chart-axis', '#a8a29e'),
              font: { family: cssVar('--font-mono') || 'ui-monospace', size: 10 },
              padding: 4,
              stepSize: yStep,
              callback(v) {
                const d = v - 1;
                return `${d >= 0 ? '+' : ''}${(d * 100).toFixed(0)}%`;
              },
            },
          },
        },
        layout: { padding: { top: 8, right: 4, bottom: 0, left: 4 } },
      },
    });
    chartRegistry.add(histChart);

    // x-label strip: 4 evenly spaced points
    const xWrap = document.getElementById('history-xlabels');
    if (xWrap) {
      const fmt = currentRange === '1Y' ? monthLabel : shortDate;
      const n = allDates.length;
      if (n === 0) {
        xWrap.innerHTML = '';
      } else {
        const picks = [0, Math.floor(n / 3), Math.floor((2 * n) / 3), n - 1]
          .filter((i, idx, arr) => arr.indexOf(i) === idx);
        xWrap.innerHTML = picks.map((i) => `<span>${fmt(allDates[i])}</span>`).join('');
      }
    }

    // a11y summary — series are TWR-rebased to 1.0, so (last - 1) is the cumulative return.
    const summary = portReturn != null
      ? `${range} TWR ${pctStr(portReturn)}. 벤치마크 ${benchName} ${benchReturn != null ? pctStr(benchReturn) : '—'}.`
      : '데이터 없음';
    document.getElementById('history-summary').textContent = summary;
    wrap.setAttribute('aria-busy', 'false');
  }

  // react to orientation / narrow changes
  narrow.addEventListener?.('change', () => {
    if (histChart) {
      histChart.options.aspectRatio = narrow.matches ? 1.3 : 2.4;
      histChart.update('none');
    }
  });

  // ---------- dispatch ----------

  const page = document.body?.dataset?.page;
  const reloaders = {
    overview: renderOverview,
    account: renderAccount,
  };

  async function loadAll() {
    const fn = reloaders[page];
    if (!fn) return;
    try {
      await fn();
    } catch (e) {
      console.error(e);
      Alpine.store('toast').push('데이터를 불러오지 못했습니다', 'error');
    }
  }

  window.pageReload = loadAll;

  // kick off after DOM ready (body is parsed by the time defer script runs)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadAll);
  } else {
    loadAll();
  }

  // auto-refresh every 15 minutes
  setInterval(loadAll, 15 * 60 * 1000);

  // register service worker (no-op on non-secure origins / http)
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
    });
  }
})();
