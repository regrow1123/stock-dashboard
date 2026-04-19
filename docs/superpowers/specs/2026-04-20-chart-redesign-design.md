# Chart Redesign — Editorial Mono

Status: Approved for planning
Date: 2026-04-20
Scope: Account detail page history chart (`/accounts/{id}`). Portfolio vs benchmark line chart only. No data/API changes.

## Motivation

Current chart is Chart.js default: blue solid line + muted dashed gray benchmark, index-mode tooltip, raw multiplier y-axis, Pretendard labels. It reads as generic fintech template with no distinct aesthetic. The rest of the site shares the same generic tone but the chart is the most prominent visual element on the account page — fixing it first gives the biggest visual payoff.

## Aesthetic direction

**Editorial Mono.** Inspired by magazine/annual-report data treatments: cream paper, ink-black line, serif numerals, mono technical labels. Dark mode pairs this with a deep neutral (near-black #0c0c0e) and lime accent — evokes a trader terminal without the dense-grid clutter.

The chart's personality comes from typography contrast: a single bold serif number on a mostly-empty canvas, with mono for the technical metadata (date, range, ticker, axis labels).

## Visual Specification

### Card layout (top to bottom)

1. **Header row** — title ("자산 추이 · vs KOSPI") left; range chip group ("1M 3M 6M 1Y") right. Chips may wrap below the title on narrow widths; this is acceptable.
2. **Stats row** — serif display number for portfolio TWR (+12.4%); mono secondary text for benchmark TWR (KOSPI +4.1%).
3. **Plot area** — line chart (see Chart spec).
4. **X-axis label strip** — mono labels; month-only for 1Y range, 'YY-MM for 1M/3M/6M.

No caption, no legend, no axis titles. The stats row replaces the legend — reader infers line = main, dashed = benchmark.

### Typography

| Role | Font | Size | Weight | Other |
|---|---|---|---|---|
| Hero % number | IBM Plex Serif | 28px (clamp 24-32px) | 500 | letter-spacing -0.02em, tabular-nums |
| Benchmark secondary % | JetBrains Mono | 14px | 600 | tabular-nums |
| Section title | JetBrains Mono | 11px | 600 | uppercase, letter-spacing 0.08em |
| Chip | JetBrains Mono | 11px | 600 | letter-spacing 0.05em |
| Axis labels (x) | JetBrains Mono | 10px | 400 | - |
| Tooltip card | JetBrains Mono | 9-11px | 400-600 | tabular-nums |

Fonts loaded via jsDelivr with preconnect. IBM Plex Serif 500 + JetBrains Mono 400/600 only — two weights each, not full families.

### Color tokens

New tokens added to `web/styles.src.css` `@theme` block. Existing `--color-*` tokens remain for non-chart components.

| Token | Light | Dark |
|---|---|---|
| --chart-card-bg | #fafaf7 | #0c0c0e |
| --chart-card-border | #e8e6df | #1f1f23 |
| --chart-title | #78716c | #71717a |
| --chart-tag | #a8a29e | #a1a1aa |
| --chart-hero | #1c1917 | #fafafa |
| --chart-hero-pos | #1c1917 | #a3e635 |
| --chart-hero-neg | #b91c1c | #fb7185 |
| --chart-line | #1c1917 | #fafafa |
| --chart-line-bench | #a8a29e | #71717a |
| --chart-axis | #a8a29e | #52525b |
| --chart-grid | #e8e6df | #1f1f23 |
| --chart-marker | #1c1917 | #a3e635 |
| --chart-tooltip-bg | #ffffff | #18181b |
| --chart-tooltip-border | #e8e6df | #27272a |

Fill gradient: `--chart-line` at 15% opacity top → 0% bottom.

### Chart spec (Chart.js 4)

- **Portfolio dataset**: line, `borderColor: --chart-line`, `borderWidth: 1.5`, smooth curve `tension: 0.18`, no points (pointRadius 0), area fill with vertical gradient (15% → 0%).
- **Benchmark dataset**: line, `borderColor: --chart-line-bench`, `borderWidth: 1`, `borderDash: [2, 3]`, no fill, no points.
- **Y-axis**: hidden (`display: false`). Values are available via tooltip.
- **X-axis**: displayed, no grid lines. Labels formatted based on range:
  - `1Y` → Korean month labels (`"4월"`, `"8월"`, etc.) — sample 4 points max on narrow, 6 on wide.
  - `1M / 3M / 6M` → `'YY-MM` mono.
- **Animations**: 220ms (respects `prefers-reduced-motion`, same as current).
- **aspectRatio**: 1.3 narrow / 2.4 wide (same as current).

### Interactions

**Idle state** (no hover):
- Small filled dot at the last portfolio point, colored with `--chart-marker` (ink on light, lime on dark). Radius 3px.

**Hover state** (mouse or touch):
- Vertical dashed crosshair line at the nearest x, color `--chart-axis`, width 0.5px, `dashArray: [2, 2]`.
- Two small dots at the x: portfolio point (white/ink outlined) and benchmark point (muted).
- Floating tooltip card anchored near the crosshair (auto-flipping to avoid right edge), rendered as a DOM element (Chart.js `tooltip.external`), not the built-in canvas tooltip:
  ```
  ┌────────────────────┐
  │ 2025-12-08         │  ← mono, muted
  │ PORT  +8.92%       │  ← mono, pos/neg colored
  │ BMK   +3.10%       │
  └────────────────────┘
  ```
  3 lines, 10-13px, `--chart-tooltip-bg` with 1px `--chart-tooltip-border`, `border-radius: 6px`, subtle shadow.

**Touch**: same tooltip triggered on tap/drag. Tooltip stays until next tap or scroll.

### Range chips

Segmented pill matching current `.chip-group` but with slight editorial tweaks:
- Font: JetBrains Mono (currently Pretendard).
- Active state: background `--chart-card-border` (subtle), text `--chart-hero`.
- On narrow widths the chip group wraps to its own row below the title — acceptable, no scroll.

Existing `.chip` / `.chip-group` classes stay for non-chart use (currency switch on overview). Chart chips get a scoped variant (`.chip-mono` or reuse with a modifier).

## Implementation

### Files touched

- `web/styles.src.css` — add chart tokens, mono chip variant, tooltip card CSS. Compile to `web/static/styles.css`.
- `web/static/app.js` — rewrite `renderAccountHistory` chart config. Add one Chart.js plugin for the idle last-point dot and crosshair. Add external tooltip renderer (vanilla DOM, Alpine-free).
- `web/templates/account.html` — template markup adjusted to move chips into the chart card header and remove the section heading above.
- `web/templates/base.html` — add font preconnect/stylesheet for IBM Plex Serif + JetBrains Mono (jsDelivr or a similar CDN; use one provider).
- No Python / API / scheduler changes.

### Chart.js plugin (single file-local plugin)

One inline plugin in `app.js`, not a separate module — it's small and chart-specific:

```js
const chartOrnamentsPlugin = {
  id: 'ornaments',
  afterDatasetsDraw(chart) {
    // 1. idle last-point marker (only when no tooltip active)
    // 2. crosshair vertical line (when tooltip active)
  },
};
```

Tooltip content is rendered by a separate `externalTooltip(context)` function that mutates a single DOM element appended inside `#history-wrap`.

### Font loading

Add to `base.html` `<head>`:
```html
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-serif@5.0.8/500.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5.0.18/400.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5.0.18/600.css">
```

Existing Pretendard Variable link stays. All three font faces set `font-display: swap`.

### Chart redraw on theme change

Current `darkMq.addEventListener('change', redrawCharts)` already re-reads CSS vars — confirmed to work for the new tokens as long as we read via `colorOf('--chart-*')` in the chart build function (not cached at module load).

### Accessibility

- sr-only summary (already present) rewritten: "1Y TWR +12.4%. 벤치마크 KOSPI +4.1%."
- Hero number gets `role="text"` grouping so screen readers don't announce percent symbol separately.
- Crosshair and marker are `aria-hidden` (decorative).
- Chips remain `role="tablist"` + `aria-selected` (no change).
- Reduced motion disables animations (already present).
- Color contrast: all text ≥4.5:1 on its background in both themes (verified pairings above).

## Non-goals

- Multi-account comparison chart — not in scope.
- Changing rebase math (TWR) — data layer unchanged.
- Scrub-drag history reading on mobile — tap-to-show tooltip is enough.
- Replacing charts on Overview page — the overview doesn't render this chart. Stays as-is for now.
- Candlesticks / drawdown overlays — future.
- Updating other dashboard pages to editorial tone — this spec is chart-only. Separate pass later.

## Testing

- Manual verification in browser (Chromium, Safari if available) at narrow (375px) and wide (1024px), light and dark.
- Verify range switch triggers chart rebuild without leaking old Chart instances (already handled).
- Verify OS theme toggle triggers a redraw with correct tokens.
- No new unit tests — the added JS is view-layer only; existing tests cover data functions.

## Rollout

Single PR. Docker rebuild required (`COPY`-based image). Service worker cache bust handled by `asset_ver` query param (already present).
