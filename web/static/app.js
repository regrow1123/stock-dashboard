// Stock-dashboard frontend controller.
// Routes based on <body data-page="…">. Shared Alpine stores and utilities.

(() => {
  'use strict';

  // ---------- utilities ----------

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

  const monthDay = (iso) => iso.slice(5, 10); // 'MM-DD'

  const timeLabel = (date = new Date()) =>
    date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });

  async function getJSON(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }

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
      _onScroll: null,
      init() {
        this._onScroll = () => { this.scrolled = window.scrollY > 8; };
        window.addEventListener('scroll', this._onScroll, { passive: true });
        this._onScroll();
      },
      destroy() {
        window.removeEventListener('scroll', this._onScroll);
      },
    }));
  });

  // ---------- helpers ----------

  function escapeHTML(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
  }

  // ---------- Overview ----------

  async function renderOverview() {
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

  // Semicircle dial (CNN-style). One shared component, used for both F&G
  // (0..100, red→green) and SKEW (100..160, green→red).
  function dialCard({ title, ariaLabel, score, scoreFmt, rating, lo, hi,
                       gradientId, ticks, reversed, history, scoreDecimals = 0 }) {
    const cx = 120, cy = 110, r = 95;
    const clamp = (v) => Math.max(lo, Math.min(hi, v));
    const polar = (v) => {
      const t = (clamp(v) - lo) / (hi - lo);
      const a = Math.PI * (1 - t);
      return { x: cx + r * Math.cos(a), y: cy - r * Math.sin(a), a };
    };
    const tickLine = (v) => {
      const inner = polar(v);
      const ox = cx + (r + 6) * Math.cos(inner.a);
      const oy = cy - (r + 6) * Math.sin(inner.a);
      return `<line x1="${inner.x.toFixed(1)}" y1="${inner.y.toFixed(1)}" x2="${ox.toFixed(1)}" y2="${oy.toFixed(1)}"></line>`;
    };
    const histDot = (entry) => {
      const { value, label } = entry;
      if (value == null) return '';
      const { x, y } = polar(value);
      const text = `${label} ${value.toFixed(scoreDecimals)}`;
      return `<g class="fg-hist">
        <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5"></circle>
        <text x="${x.toFixed(1)}" y="${(y - 9).toFixed(1)}" text-anchor="middle">${escapeHTML(text)}</text>
      </g>`;
    };
    // tapered needle: triangle from hub (wide) to tip (sharp)
    const needle = polar(score);
    const baseHalf = 5;
    const pdx = Math.sin(needle.a);
    const pdy = Math.cos(needle.a);
    const bx1 = (cx + baseHalf * pdx).toFixed(1);
    const by1 = (cy + baseHalf * pdy).toFixed(1);
    const bx2 = (cx - baseHalf * pdx).toFixed(1);
    const by2 = (cy - baseHalf * pdy).toFixed(1);

    const stops = reversed
      ? [['0','#16a34a'],['0.3','#84cc16'],['0.55','#facc15'],['0.75','#f59e0b'],['1','#dc2626']]
      : [['0','#dc2626'],['0.3','#f59e0b'],['0.5','#facc15'],['0.7','#84cc16'],['1','#16a34a']];

    return `
      <div class="sent-card fg-dial-card">
        <div class="sent-head">
          <span class="sent-lbl">${escapeHTML(title)}</span>
          <span class="sent-score">${escapeHTML(scoreFmt)}<span class="sent-rating"> · ${escapeHTML(rating)}</span></span>
        </div>
        <svg class="fg-dial" viewBox="0 0 240 140" role="img" aria-label="${escapeHTML(ariaLabel)}">
          <defs>
            <linearGradient id="${gradientId}" x1="0" x2="1" y1="0" y2="0">
              ${stops.map(([o,c]) => `<stop offset="${o}" stop-color="${c}"/>`).join('')}
            </linearGradient>
          </defs>
          <path class="fg-arc-bg"
                d="M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}"/>
          <path class="fg-arc" style="stroke: url(#${gradientId})"
                d="M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}"/>
          ${ticks.map(tickLine).join('')}
          ${history.map(histDot).join('')}
          <polygon class="fg-needle"
                   points="${needle.x.toFixed(1)},${needle.y.toFixed(1)} ${bx1},${by1} ${bx2},${by2}"/>
          <circle class="fg-hub" cx="${cx}" cy="${cy}" r="5"/>
        </svg>
      </div>`;
  }

  function fgDialCard(fg) {
    const score = Math.round(fg.score);
    return dialCard({
      title: 'CNN Fear & Greed',
      ariaLabel: `Fear and Greed ${score} of 100, ${fgRatingKo(fg.rating)}`,
      score,
      scoreFmt: String(score),
      rating: fgRatingKo(fg.rating),
      lo: 0, hi: 100,
      gradientId: 'fg-arc-grad',
      ticks: [0, 25, 50, 75, 100],
      reversed: false,
      history: [
        { value: fg.previous_1_month != null ? Math.round(fg.previous_1_month) : null, label: '1달' },
        { value: fg.previous_1_week  != null ? Math.round(fg.previous_1_week)  : null, label: '1주' },
        { value: fg.previous_close   != null ? Math.round(fg.previous_close)   : null, label: '어제' },
      ],
      scoreDecimals: 0,
    });
  }

  function skewSparkCard(sk) {
    const hist = (sk.history || []).filter((p) => p.score != null);
    if (hist.length < 2) return '';
    // tight y-range with small padding
    const vals = hist.map((p) => p.score);
    const dataMin = Math.min(...vals);
    const dataMax = Math.max(...vals);
    const pad = Math.max(1, (dataMax - dataMin) * 0.08);
    const yMin = dataMin - pad;
    const yMax = dataMax + pad;
    // viewBox geometry
    const W = 300, H = 70, PX = 4, PY = 4;
    const xStep = (W - 2 * PX) / (hist.length - 1);
    const yAt = (v) => PY + (yMax - v) / (yMax - yMin) * (H - 2 * PY);
    const xAt = (i) => PX + i * xStep;
    const points = hist.map((p, i) => `${xAt(i).toFixed(1)},${yAt(p.score).toFixed(1)}`);
    const pathD = `M ${points.join(' L ')}`;
    // area fill: extend path down to bottom
    const areaD = `M ${PX},${H - PY} L ${points.join(' L ')} L ${(W - PX).toFixed(1)},${H - PY} Z`;
    // last point
    const lastX = xAt(hist.length - 1);
    const lastY = yAt(hist[hist.length - 1].score);
    // zone boundaries (in SKEW units): 115 / 130 / 145. Only draw those within view.
    const zoneLines = [115, 130, 145]
      .filter((v) => v >= yMin && v <= yMax)
      .map((v) => {
        const y = yAt(v);
        return `<line class="sk-zone-line" x1="0" y1="${y.toFixed(1)}" x2="${W}" y2="${y.toFixed(1)}"/>`;
      })
      .join('');

    const firstDate = hist[0].date;
    const lastDate = hist[hist.length - 1].date;
    const label = skewLabel(sk.score);

    return `
      <div class="sent-card">
        <div class="sent-head">
          <span class="sent-lbl">CBOE SKEW · 꼬리위험</span>
          <span class="sent-score">${sk.score.toFixed(1)}<span class="sent-rating"> · ${escapeHTML(label)}</span></span>
        </div>
        <svg class="sk-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
             aria-label="SKEW 60일 추이, 현재 ${sk.score.toFixed(1)}">
          ${zoneLines}
          <path class="sk-area" d="${areaD}"/>
          <path class="sk-line" d="${pathD}"/>
          <circle class="sk-dot" cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="3"/>
        </svg>
        <div class="sk-xlabels">
          <span>${escapeHTML(firstDate.slice(2))}</span>
          <span>${escapeHTML(lastDate.slice(2))}</span>
        </div>
      </div>`;
  }

  function skewLabel(score) {
    if (score == null) return '';
    if (score < 115) return '낮음';
    if (score < 130) return '평이';
    if (score < 145) return '높음';
    return '매우 높음';
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
    const cards = [];
    const fg = data.fear_and_greed;
    if (fg && fg.score != null) {
      cards.push(fgDialCard(fg));
    }
    const sk = data.skew;
    if (sk && sk.score != null) {
      cards.push(skewSparkCard(sk));
    }
    host.innerHTML = cards.join('');
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

  async function renderAccount() {
    await Promise.all([
      renderAccountSectors(),
      renderAccountWeights(),
      renderAccountHoldings(),
      renderAccountPostSells(),
      renderAccountTrades(),
    ]);
  }

  const SECTOR_COLORS = [
    '#5b8def', '#34c759', '#ff9f0a', '#ff453a', '#bf5af2',
    '#5ac8fa', '#ffd60a', '#ff6482', '#64d2ff', '#30d158', '#8e8e93',
  ];

  async function renderAccountSectors() {
    const host = document.getElementById('sectors');
    if (!host) return;
    let data;
    try { data = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/sectors`); }
    catch (e) { host.removeAttribute('aria-busy'); host.innerHTML = ''; return; }
    const items = data.items || [];
    if (!items.length) {
      host.removeAttribute('aria-busy');
      host.innerHTML = `<div class="row-sub">보유 종목이 없습니다.</div>`;
      return;
    }
    const segs = items.map((it, i) => {
      const c = SECTOR_COLORS[i % SECTOR_COLORS.length];
      return `<span class="sector-seg" style="width:${(it.weight * 100).toFixed(2)}%;background:${c}"></span>`;
    }).join('');
    const legend = items.map((it, i) => {
      const c = SECTOR_COLORS[i % SECTOR_COLORS.length];
      return `<li class="sector-legend-row">
        <span class="sector-dot" style="background:${c}"></span>
        <span class="sector-name">${escapeHTML(it.sector)}</span>
        <span class="sector-weight">${(it.weight * 100).toFixed(1)}%</span>
      </li>`;
    }).join('');
    host.removeAttribute('aria-busy');
    host.innerHTML = `
      <div class="sector-bar" role="img" aria-label="섹터 비중 막대 차트">${segs}</div>
      <ul class="sector-legend">${legend}</ul>`;
  }

  async function renderAccountPostSells() {
    const host = document.getElementById('post-sells');
    if (!host) return;
    let data;
    try {
      data = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/post_sells`);
    } catch (e) {
      host.innerHTML = '';
      return;
    }
    const items = data.items || [];
    const cur = data.currency || window.ACCOUNT_CURRENCY;
    if (!items.length) {
      host.innerHTML = `<div class="row-sub" style="padding: 0 0.25rem">최근 3개월 매도 내역이 없습니다.</div>`;
      return;
    }
    const rows = items.map((it) => {
      const ret = it.return_pct;
      const pillCls = ret == null ? 'pill-muted' : ret >= 0 ? 'pill-pos' : 'pill-neg';
      const pillText = ret == null ? '—' : pctStr(ret);
      const sub = `${monthDay(it.sold_at)} 매도 ${fmtMoney(it.sold_price, cur, { fraction: 2 })}` +
        (it.current_price != null ? ` → ${fmtMoney(it.current_price, cur, { fraction: 2 })}` : '');
      return `
        <li class="row-item">
          <div>
            <div class="row-title">${escapeHTML(it.name || it.ticker)}
              ${it.name ? `<span class="row-sub" style="display:inline; margin-left:.4rem">${escapeHTML(it.ticker)}</span>` : ''}
            </div>
            <div class="row-sub">${sub}</div>
          </div>
          <div class="row-right">
            <span class="pill ${pillCls}">${pillText}</span>
          </div>
        </li>`;
    }).join('');
    host.innerHTML = `<ul class="row-list">${rows}</ul>`;
  }

  async function renderAccountWeights() {
    const rows = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/weights`);
    const wrap = document.getElementById('weights');
    wrap.setAttribute('aria-busy', 'false');
    if (!rows.length) {
      wrap.innerHTML = `<div class="row-sub">보유 종목 없음</div>`;
      return;
    }
    const WINDOWS = [5, 10, 20];
    // a weight delta in pp → signed text; negligible (<0.05pp) is hushed to "—"
    const wcCell = (wc) => {
      const cls = wc == null ? 'muted' : wc >= 0 ? 'pos' : 'neg';
      const text = wc == null || Math.abs(wc) < 0.0005
        ? '—'
        : `${wc >= 0 ? '+' : ''}${(wc * 100).toFixed(1)}`;
      return `<span class="wc-cell ${cls}">${text}</span>`;
    };
    const top = [...rows].sort((a, b) => b.weight - a.weight).slice(0, 10);
    const header = `
      <div class="weight-head" aria-hidden="true">
        <span class="wc-grid">${WINDOWS.map((n) => `<span class="wc-cell">${n}일</span>`).join('')}</span>
      </div>`;
    wrap.innerHTML = header + top.map((r) => {
      const cells = WINDOWS.map((n) => wcCell(r[`change_${n}d`])).join('');
      const ariaChanges = WINDOWS
        .map((n) => `${n}일 ${r[`change_${n}d`] == null ? '—' : (r[`change_${n}d`] * 100).toFixed(2) + '%p'}`)
        .join(' ');
      const aria = `${escapeHTML(r.name || r.ticker)} ${pctInt(r.weight)} 비중변화 ${ariaChanges}`;
      return `
      <div class="weight-row" aria-label="${aria}">
        <span class="label-txt">${escapeHTML(r.name || r.ticker)}</span>
        <span class="pct">${pctInt(r.weight)}</span>
        <span class="wc-grid" aria-hidden="true">${cells}</span>
        <div class="weight-bar" aria-hidden="true">
          <span style="width: ${(r.weight * 100).toFixed(1)}%"></span>
        </div>
      </div>`;
    }).join('');
  }

  async function renderAccountHoldings() {
    const rows = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/holdings`);
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
        const price = r.current_price != null
          ? fmtMoney(r.current_price, cur, { fraction: 2 })
          : '—';
        const name = escapeHTML(r.name || r.ticker);
        const qty = r.quantity % 1 === 0 ? r.quantity : r.quantity.toFixed(4).replace(/\.?0+$/, '');
        return `
          <li>
            <button type="button" class="row-item" data-ticker="${escapeHTML(r.ticker)}"
                    data-name="${name}"
                    aria-label="${name} ${qty}주, 매매내역 보기">
              <div>
                <div class="row-title">${name}</div>
                <div class="row-sub">${escapeHTML(r.ticker)} · ${qty}주</div>
              </div>
              <div class="row-right">
                ${price}
                <div class="row-sub"><span class="pill ${dcPill}">${dcText}</span></div>
              </div>
            </button>
          </li>`;
      }).join('');
      if (!list.dataset.wired) {
        list.addEventListener('click', (e) => {
          const btn = e.target.closest('button[data-ticker]');
          if (!btn) return;
          setTickerFilter(btn.dataset.ticker, btn.dataset.name);
        });
        list.dataset.wired = '1';
      }
    }

  }

  let allTrades = [];
  let tickerFilter = null;      // ticker string when filtered
  let tickerFilterName = null;  // display name

  async function renderAccountTrades() {
    allTrades = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/trades?limit=200`);
    redrawTrades();
  }

  function setTickerFilter(ticker, name) {
    tickerFilter = ticker;
    tickerFilterName = name || ticker;
    redrawTrades();
    document.getElementById('trades-heading')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function clearTickerFilter() {
    tickerFilter = null;
    tickerFilterName = null;
    redrawTrades();
  }

  function redrawTrades() {
    const cur = window.ACCOUNT_CURRENCY;
    const rows = tickerFilter
      ? allTrades.filter((t) => t.ticker === tickerFilter)
      : allTrades.slice(0, 20);
    const banner = document.getElementById('trades-filter');
    if (banner) {
      if (tickerFilter) {
        banner.innerHTML = `
          <button type="button" class="trades-filter-chip" aria-label="필터 해제">
            ${escapeHTML(tickerFilterName)} 만 보기
            <span aria-hidden="true">×</span>
          </button>`;
        banner.hidden = false;
        banner.querySelector('button').onclick = clearTickerFilter;
      } else {
        banner.innerHTML = '';
        banner.hidden = true;
      }
    }

    const list = document.getElementById('trades-list');
    list.setAttribute('aria-busy', 'false');
    if (!rows.length) {
      const msg = tickerFilter ? `${tickerFilterName} 거래 내역 없음` : '거래 내역이 없습니다';
      list.innerHTML = `<li class="row-item"><div><div class="row-title">${escapeHTML(msg)}</div></div></li>`;
      return;
    }
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
