# Chart Redesign — Editorial Mono — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the account-page history chart to an editorial-mono aesthetic (cream/ink in light, deep-neutral/lime in dark) with serif hero numbers, mono labels, gradient area fill, an idle last-point marker, and a custom DOM-based hover tooltip.

**Architecture:** Frontend-only change. Pure HTML/CSS/JS — no Python, no API, no DB, no schema, no test code (existing tests cover data layer). Chart logic lives in one inline plugin + one tooltip renderer added to the existing `renderAccountHistory` function in `web/static/app.js`. Tailwind v4 is configured with `@source` so new utility classes are picked up at build time without config changes; bespoke component CSS goes into `web/styles.src.css`.

**Tech Stack:** Tailwind CSS v4, Chart.js 4, Alpine.js 3 (unchanged), Pretendard Variable + IBM Plex Serif + JetBrains Mono (added).

---

## Files Touched

- `web/templates/base.html` — font CDN links
- `web/styles.src.css` — design tokens, chart card CSS, mono chip variant, tooltip card CSS
- `web/templates/account.html` — restructure `<section aria-labelledby="history-heading">`
- `web/static/app.js` — rewrite chart config in `renderAccountHistory`, add `chartOrnamentsPlugin`, add `externalTooltip` renderer

CSS is compiled to `web/static/styles.css` via `npm run build:css`. Run `npm run watch:css` during development.

The dev server is started locally with `.venv/bin/uvicorn app.main:create_app --factory --port 8080` (loads `.env` automatically). Verify in a browser at http://localhost:8080/accounts/1 (replace `1` with any account id from the seed YAML). Toggle the OS theme to test dark mode (System Settings → Appearance, or browser devtools `Rendering → Emulate CSS prefers-color-scheme`).

Before starting: ensure `npm install` was run at least once (creates `node_modules` for Tailwind CLI). Each task below assumes `npm run watch:css` is running in a side terminal.

---

## Task 1: Add font CDN links

**Files:**
- Modify: `web/templates/base.html`

- [ ] **Step 1: Read the current `<head>` block to find the existing Pretendard `<link>` line**

Run: `grep -n "stylesheet" web/templates/base.html`
Expected output includes the Pretendard line at ~line 21-22.

- [ ] **Step 2: Add IBM Plex Serif (500) and JetBrains Mono (400, 600) right after the Pretendard `<link>`**

In `web/templates/base.html`, locate the `<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard...">` and add three lines immediately after it:

```html
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-serif@5/500.css">
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5/400.css">
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5/600.css">
```

The `preconnect` to `cdn.jsdelivr.net` is already present and covers these.

- [ ] **Step 3: Verify in browser**

Reload the dashboard. Open DevTools → Network → filter "font". Confirm `ibm-plex-serif` and `jetbrains-mono` woff2 files load with status 200.

In the Console, paste:

```js
document.fonts.check('14px "IBM Plex Serif"') && document.fonts.check('14px "JetBrains Mono"')
```

Expected output: `true`.

- [ ] **Step 4: Commit**

```bash
git add web/templates/base.html
git commit -m "feat(web): add IBM Plex Serif + JetBrains Mono for chart"
```

---

## Task 2: Add chart design tokens

**Files:**
- Modify: `web/styles.src.css` (the `@theme` block, lines ~7-37, and the dark `@media` block, lines ~40-60)

- [ ] **Step 1: Add chart tokens to the `@theme` block (light defaults)**

In `web/styles.src.css`, inside the existing `@theme { ... }` block, after the existing `--color-negative-soft` line and before `--shadow-card`, add:

```css
  /* chart-specific tokens — Editorial Mono */
  --chart-card-bg:       #fafaf7;
  --chart-card-border:   #e8e6df;
  --chart-title:         #78716c;
  --chart-tag:           #a8a29e;
  --chart-hero:          #1c1917;
  --chart-hero-pos:      #1c1917;
  --chart-hero-neg:      #b91c1c;
  --chart-line:          #1c1917;
  --chart-line-bench:    #a8a29e;
  --chart-axis:          #a8a29e;
  --chart-grid:          #e8e6df;
  --chart-marker:        #1c1917;
  --chart-tooltip-bg:    #ffffff;
  --chart-tooltip-border:#e8e6df;
```

- [ ] **Step 2: Add dark overrides**

In the same file, inside `@media (prefers-color-scheme: dark) { :root { ... } }`, after `--color-negative-soft: #3b1111;` and before `--shadow-card`, add:

```css
    --chart-card-bg:       #0c0c0e;
    --chart-card-border:   #1f1f23;
    --chart-title:         #71717a;
    --chart-tag:           #a1a1aa;
    --chart-hero:          #fafafa;
    --chart-hero-pos:      #a3e635;
    --chart-hero-neg:      #fb7185;
    --chart-line:          #fafafa;
    --chart-line-bench:    #71717a;
    --chart-axis:          #52525b;
    --chart-grid:          #1f1f23;
    --chart-marker:        #a3e635;
    --chart-tooltip-bg:    #18181b;
    --chart-tooltip-border:#27272a;
```

- [ ] **Step 3: Verify the CSS rebuilds without error**

If `npm run watch:css` is running in another terminal, look for a green "Done in N ms" line. Otherwise run:

```bash
npm run build:css
```

Expected: exit 0, no warnings about unknown @theme values.

- [ ] **Step 4: Commit**

```bash
git add web/styles.src.css web/static/styles.css
git commit -m "feat(web): add Editorial Mono chart design tokens"
```

---

## Task 3: Add chart card + tooltip CSS

**Files:**
- Modify: `web/styles.src.css` (append inside the existing `@layer components { ... }` block)

- [ ] **Step 1: Append chart card and tooltip styles to `@layer components`**

In `web/styles.src.css`, find the closing `}` of the `@layer components { ... }` block (look for `@keyframes skeleton-shimmer { ... } }` near line ~436). Just before that final `}`, paste:

```css
  /* ===== Chart card (editorial-mono) ===== */
  .chart-card {
    background: var(--chart-card-bg);
    border: 1px solid var(--chart-card-border);
    border-radius: var(--radius-lg);
    padding: 1.125rem 1.25rem 0.875rem;
    overflow: hidden;
  }
  .chart-card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
  }
  .chart-card-title {
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--chart-title);
    font-weight: 600;
    margin: 0;
  }
  .chart-card-stats {
    display: flex;
    align-items: baseline;
    gap: 1rem;
    margin-bottom: 0.625rem;
    font-variant-numeric: tabular-nums;
  }
  .chart-hero {
    font-family: "IBM Plex Serif", Georgia, serif;
    font-weight: 500;
    font-size: clamp(1.5rem, 5vw, 1.75rem);
    letter-spacing: -0.02em;
    color: var(--chart-hero);
    line-height: 1;
  }
  .chart-hero.pos { color: var(--chart-hero-pos); }
  .chart-hero.neg { color: var(--chart-hero-neg); }
  .chart-stat-bench {
    font-family: var(--font-mono);
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--chart-title);
  }

  /* mono chip variant — used for chart range tabs */
  .chip-group-mono { background: transparent; border-color: var(--chart-card-border); }
  .chip-group-mono .chip {
    font-family: var(--font-mono);
    letter-spacing: 0.05em;
    color: var(--chart-title);
    min-height: 28px;
    padding: 4px 10px;
    font-size: 0.6875rem;
  }
  .chip-group-mono .chip[aria-selected="true"] {
    background: var(--chart-card-border);
    color: var(--chart-hero);
    box-shadow: none;
  }

  /* tooltip card — rendered as a DOM element, positioned by JS */
  .chart-tooltip {
    position: absolute;
    pointer-events: none;
    background: var(--chart-tooltip-bg);
    border: 1px solid var(--chart-tooltip-border);
    border-radius: 6px;
    padding: 8px 10px;
    box-shadow: var(--shadow-card);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    line-height: 1.45;
    color: var(--color-fg);
    z-index: 5;
    white-space: nowrap;
    opacity: 0;
    transition: opacity 100ms var(--ease-out);
    transform: translate(-50%, calc(-100% - 12px));
  }
  .chart-tooltip.is-visible { opacity: 1; }
  .chart-tooltip .tt-date { color: var(--chart-title); margin-bottom: 2px; }
  .chart-tooltip .tt-row {
    display: flex; justify-content: space-between; gap: 1.25rem;
  }
  .chart-tooltip .tt-row .tt-key { color: var(--chart-title); }
  .chart-tooltip .tt-row .tt-val { font-weight: 600; }
  .chart-tooltip .tt-val.pos { color: var(--chart-hero-pos); }
  .chart-tooltip .tt-val.neg { color: var(--chart-hero-neg); }

  /* x-axis label strip below the canvas */
  .chart-xlabels {
    display: flex;
    justify-content: space-between;
    margin-top: 0.25rem;
    font-family: var(--font-mono);
    font-size: 0.625rem;
    color: var(--chart-axis);
  }

  /* wrapper that hosts canvas + tooltip absolute positioning */
  .chart-canvas-wrap { position: relative; }
```

- [ ] **Step 2: Rebuild CSS**

If `watch:css` isn't running:

```bash
npm run build:css
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add web/styles.src.css web/static/styles.css
git commit -m "feat(web): chart card, mono chip, tooltip card styles"
```

---

## Task 4: Restructure account.html chart section

**Files:**
- Modify: `web/templates/account.html` (lines ~24-38, the `<section aria-labelledby="history-heading">` block)

- [ ] **Step 1: Replace the history section markup**

In `web/templates/account.html`, find the section that starts with `<section aria-labelledby="history-heading">` (around line 24) and ends at the matching `</section>` (around line 38). Replace the entire block with:

```html
<section aria-labelledby="history-heading">
  <h2 id="history-heading" class="sr-only">자산 추이 vs 벤치마크</h2>
  <div class="chart-card" id="history-wrap" aria-busy="true">
    <div class="chart-card-head">
      <span class="chart-card-title" id="history-title">자산 추이 · vs —</span>
      <div class="chip-group chip-group-mono" role="tablist" aria-label="기간 선택" id="range-tabs">
        <button type="button" class="chip" role="tab" data-range="1M">1M</button>
        <button type="button" class="chip" role="tab" data-range="3M">3M</button>
        <button type="button" class="chip" role="tab" data-range="6M">6M</button>
        <button type="button" class="chip" role="tab" data-range="1Y" aria-selected="true">1Y</button>
      </div>
    </div>
    <div class="chart-card-stats">
      <span id="history-hero" class="chart-hero">—</span>
      <span id="history-bench-stat" class="chart-stat-bench">—</span>
    </div>
    <div class="chart-canvas-wrap">
      <canvas id="history" role="img" aria-labelledby="history-summary"></canvas>
    </div>
    <div id="history-xlabels" class="chart-xlabels" aria-hidden="true"></div>
    <p id="history-summary" class="sr-only">자산 추이 차트를 불러오는 중입니다.</p>
  </div>
</section>
```

- [ ] **Step 2: Verify the page renders without console errors**

Reload http://localhost:8080/accounts/1. The chart will not yet render (next task) but the card frame, title placeholder, chip group, and skeleton stats should appear in the new layout. No JS errors in console.

- [ ] **Step 3: Commit**

```bash
git add web/templates/account.html
git commit -m "feat(web): restructure history section into editorial chart card"
```

---

## Task 5: Update Chart.js dataset config and x-label strip

**Files:**
- Modify: `web/static/app.js` — the `renderAccountHistory` function (lines ~413-532)

- [ ] **Step 1: Add a tiny formatter helper near the top of the IIFE (right after the existing `pctInt` definition, ~line 28)**

Add this line:

```js
const monthLabel = (iso) => {
  // iso = 'YYYY-MM-DD' → '4월' (1Y range) or 'YY-MM' (shorter ranges)
  const [, m] = iso.split('-');
  return `${parseInt(m, 10)}월`;
};
const shortDate = (iso) => iso.slice(2, 7); // 'YY-MM'
```

- [ ] **Step 2: Update the title and stats elements at the start of `renderAccountHistory`**

Inside `renderAccountHistory`, after the `const wrap = document.getElementById('history-wrap');` line and before the existing `wrap.setAttribute('aria-busy', 'true');`, add:

```js
const titleEl = document.getElementById('history-title');
const heroEl = document.getElementById('history-hero');
const benchStatEl = document.getElementById('history-bench-stat');
```

- [ ] **Step 3: After data loads (just after `if (seq !== historyReqSeq) return; // stale...`), populate the stats and title**

Insert this block right after that early-return line:

```js
const portEndVal = bench.portfolio[bench.portfolio.length - 1]?.value;
const benchEndVal = bench.benchmark[bench.benchmark.length - 1]?.value;
const portReturn = portEndVal != null ? portEndVal - 1 : null;
const benchReturn = benchEndVal != null ? benchEndVal - 1 : null;
const benchName = bench.benchmark_name || bench.benchmark_ticker || '벤치마크';

titleEl.textContent = `자산 추이 · vs ${benchName}`;
if (portReturn != null) {
  heroEl.textContent = pctStr(portReturn);
  heroEl.className = `chart-hero ${portReturn >= 0 ? 'pos' : 'neg'}`;
} else {
  heroEl.textContent = '—';
  heroEl.className = 'chart-hero';
}
benchStatEl.textContent = benchReturn != null
  ? `${benchName} ${pctStr(benchReturn)}`
  : `${benchName} —`;
```

- [ ] **Step 4: Replace the dataset config with editorial-mono styling**

Find the `histChart = new Chart(ctx, { ... })` block. Replace the entire `data.datasets` array and the `options` object with:

```js
const lineColor      = colorOf('--chart-line', '#1c1917');
const lineBenchColor = colorOf('--chart-line-bench', '#a8a29e');
const axisColor      = colorOf('--chart-axis', '#a8a29e');
const gridColor      = colorOf('--chart-grid', '#e8e6df');

// area gradient: built per-render via scriptable so it sizes correctly
// even when canvas.height is 0 at chart-construction time.
const portFill = (ctx) => {
  const { chart } = ctx;
  const area = chart.chartArea;
  if (!area) return hexToRgba(lineColor, 0.08); // first paint fallback
  const g = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
  g.addColorStop(0, hexToRgba(lineColor, 0.15));
  g.addColorStop(1, hexToRgba(lineColor, 0));
  return g;
};

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
        backgroundColor: portFill,
        fill: true,
        pointRadius: 0,
        pointHoverRadius: 0,
        borderWidth: 1.5,
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
        borderWidth: 1,
        tension: 0.18,
        fill: false,
      },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: true,
    aspectRatio: narrow.matches ? 1.3 : 2.4,
    interaction: { intersect: false, mode: 'index' },
    animation: reducedMotion.matches ? false : { duration: 220 },
    plugins: {
      legend: { display: false },
      tooltip: { enabled: false }, // we render our own DOM tooltip in Task 7
    },
    scales: {
      x: { display: false },
      y: { display: false },
    },
    layout: { padding: { top: 8, right: 4, bottom: 0, left: 4 } },
  },
});
```

- [ ] **Step 5: Render the x-label strip below the canvas**

After the `chartRegistry.add(histChart);` line, add:

```js
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
```

- [ ] **Step 6: Update the sr-only summary line**

Find the existing line:

```js
const summary = portEnd != null
  ? `${range} 구간 수익률 ${pctStr(portEnd - 1)}. 벤치마크 ${bench.benchmark_name || bench.benchmark_ticker} ${benchEnd != null ? pctStr(benchEnd - 1) : '—'}.`
  : '데이터 없음';
```

Replace with:

```js
const summary = portReturn != null
  ? `${range} TWR ${pctStr(portReturn)}. 벤치마크 ${benchName} ${benchReturn != null ? pctStr(benchReturn) : '—'}.`
  : '데이터 없음';
```

Also remove the now-redundant `port`, `b`, `portEnd`, `benchEnd` local declarations a few lines above (the values are already computed as `portReturn` / `benchReturn` / `portEndVal` / `benchEndVal` higher up).

- [ ] **Step 7: Verify in browser**

Reload http://localhost:8080/accounts/1.

- The hero serif % number should appear above the chart, in pos color when positive.
- Benchmark mono "KOSPI +X.XX%" appears next to it.
- Title reads `자산 추이 · vs <benchmark name>` in mono uppercase.
- Chart line is now ink-black (light) / off-white (dark) with subtle area fill, dashed muted benchmark line, no dots, no axes shown.
- Below the canvas: 4 mono labels (`4월 8월 12월 4월` for 1Y).
- No console errors.

Toggle the OS theme — the chart should redraw with dark tokens (the existing `darkMq` listener already calls `redrawCharts`). The gradient may not update perfectly on every redraw; that's acceptable, a range click rebuilds it cleanly.

- [ ] **Step 8: Commit**

```bash
git add web/static/app.js
git commit -m "feat(web): editorial chart datasets, hero stats, x-label strip"
```

---

## Task 6: Add idle last-point marker (ornaments plugin)

**Files:**
- Modify: `web/static/app.js`

- [ ] **Step 1: Define the plugin near the top of the IIFE**

Just before `// ---------- Alpine wiring ----------` (around line 48), insert:

```js
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
```

- [ ] **Step 2: Register the plugin on the chart**

In the `histChart = new Chart(ctx, { ... })` call, add a top-level `plugins` array property between `data` and `options`:

```js
histChart = new Chart(ctx, {
  type: 'line',
  data: { /* ... */ },
  plugins: [chartOrnamentsPlugin],
  options: { /* ... */ },
});
```

- [ ] **Step 3: Verify in browser**

Reload. With no hover, a small filled dot appears at the right end of the portfolio line. The dot is ink in light mode, lime in dark mode.

Hover over the chart — vertical dashed line appears, two dots mark the intersected points (portfolio larger, benchmark smaller). On move-out, the crosshair disappears and the idle marker returns.

- [ ] **Step 4: Commit**

```bash
git add web/static/app.js
git commit -m "feat(web): chart ornaments plugin (idle marker + hover crosshair)"
```

---

## Task 7: Add external DOM tooltip

**Files:**
- Modify: `web/static/app.js`

- [ ] **Step 1: Add the tooltip renderer near the other helpers (after the `escapeHTML` function, ~line 98)**

```js
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
```

- [ ] **Step 2: Wire `externalTooltip` into the chart options**

In `renderAccountHistory`'s `options.plugins.tooltip` block (currently `{ enabled: false }`), replace with:

```js
tooltip: {
  enabled: false,
  external: externalTooltip,
  mode: 'index',
  intersect: false,
},
```

- [ ] **Step 3: Verify in browser**

Reload. Hover over the chart — a small mono tooltip card appears above the crosshair with date, PORT %, BMK %. The card text uses pos/neg color. Move out — card fades out (100ms).

Resize the window — the tooltip respects the new chart dimensions and stays anchored to the crosshair.

Test on a touch device (or DevTools device toolbar): tap on the chart shows the tooltip; tapping outside hides it.

- [ ] **Step 4: Edge case — verify the card doesn't overflow on the right edge**

Hover near the right edge of the chart. The CSS uses `transform: translate(-50%, calc(-100% - 12px))` which centers the card horizontally; near the right edge it will visually overflow. If overflow is unacceptable, add this small adjust at the end of `externalTooltip`:

```js
const wrapRect = wrap.getBoundingClientRect();
const elRect = el.getBoundingClientRect();
const half = elRect.width / 2;
if (left + half > wrapRect.width) {
  el.style.left = `${wrapRect.width - half - 4}px`;
} else if (left - half < 0) {
  el.style.left = `${half + 4}px`;
}
```

(Add this before `el.classList.add('is-visible');`. If hover near edges already looks fine without it, skip — YAGNI.)

- [ ] **Step 5: Commit**

```bash
git add web/static/app.js
git commit -m "feat(web): DOM-based chart tooltip card"
```

---

## Task 8: Final cross-cutting verification

**Files:**
- None (manual verification only)

- [ ] **Step 1: Light + wide (≥1024px)**

Open http://localhost:8080/accounts/1 in a browser at desktop width, light theme.
Check:
- Title is mono uppercase, muted color.
- Range chips on the right of the title.
- Hero serif % is large, ink color when positive, deep red when negative.
- Line is ink, area fill is faint ink gradient.
- Benchmark dashed muted gray line.
- Idle dot at the right end.
- Hover shows crosshair + tooltip card.
- X-label strip shows 4 month labels (e.g. `4월 8월 12월 4월`).
- No legend, no axis labels.

- [ ] **Step 2: Dark + wide**

Toggle OS theme to dark (or DevTools `Rendering → prefers-color-scheme: dark`). Reload the page.
Check:
- Card background is near-black, border subtle.
- Hero % is lime green when positive (`#a3e635`).
- Line is off-white.
- Idle dot is lime.
- Tooltip card has dark background, mono text.

- [ ] **Step 3: Light + narrow (375px DevTools device toolbar)**

Toggle device toolbar to iPhone SE (375px). Reload.
Check:
- Chart card and chips fit. If chips wrap below the title, that's acceptable per spec.
- Hero size scales down.
- Tap on chart shows tooltip; tap elsewhere hides.
- X-label strip still readable (4 labels with at least 3 distinct visible).

- [ ] **Step 4: Dark + narrow** — repeat the same checks.

- [ ] **Step 5: Range switching**

Click each range chip in turn (`1M`, `3M`, `6M`, `1Y`).
Check:
- Active chip background changes per `aria-selected`.
- Chart smoothly rebuilds for each range.
- Hero number and benchmark text update.
- X-label format switches: `'YY-MM` for 1M/3M/6M, `N월` for 1Y.

- [ ] **Step 6: Reduced motion**

In DevTools, `Rendering → Emulate CSS media feature → prefers-reduced-motion: reduce`. Reload. Range switches should produce no animation; tooltip should appear instantly without fade.

- [ ] **Step 7: Run existing tests to confirm no regression in non-frontend code**

```bash
.venv/bin/pytest -q
```

Expected: all tests pass (frontend changes don't affect Python tests; this is a sanity check).

- [ ] **Step 8: If everything passes, push the branch**

(No commit needed at this step; the previous tasks already created focused commits.)

```bash
git status
git log --oneline -10
```

Expected: clean working tree, recent commits show the task progression.

---

## Done

Frontend chart redesign for the account page is complete. The Editorial Mono direction is now applied to the most prominent visual element on `/accounts/{id}`. Other pages (overview, holdings table, weight bars) remain on the prior style — a separate planning pass can extend the editorial direction to those if desired.
