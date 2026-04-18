const fmt = (n, cur = CURRENCY) =>
  new Intl.NumberFormat('ko-KR',
    { style: 'currency', currency: cur, maximumFractionDigits: 2 }).format(n);
const fmtInt = (n, cur = CURRENCY) =>
  new Intl.NumberFormat('ko-KR',
    { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(n);
const pctStr = n => (n >= 0 ? '+' : '') + (n * 100).toFixed(2) + '%';
const signed = (n, cur = CURRENCY) => new Intl.NumberFormat('ko-KR',
  { style: 'currency', currency: cur, signDisplay: 'always', maximumFractionDigits: 0 }).format(n);
const pctNum = n => (n * 100).toFixed(2) + '%';

let pieChart = null;
let histChart = null;

async function get(path) { return (await fetch(path)).json(); }

async function loadHeader() {
  const s = await get('/api/summary');
  const row = s.accounts.find(a => a.account_id === ACCOUNT_ID);
  if (!row) return;
  document.getElementById('header-cards').innerHTML = `
    <div class="card">
      <div class="kv"><span>수익률</span>
        <span class="pill ${row.pct_return>=0?'pos':'neg'}">${pctStr(row.pct_return)}</span>
      </div>
      <div class="kv big"><span>평가</span><strong>${fmtInt(row.value)}</strong></div>
      <div class="kv"><span>원가</span><strong>${fmtInt(row.cost)}</strong></div>
      <div class="kv"><span>평가손익</span>
        <strong class="${row.pnl>=0?'pos':'neg'}">${signed(row.pnl)}</strong>
      </div>
    </div>`;
}

async function loadHoldings() {
  const rows = await get(`/api/accounts/${ACCOUNT_ID}/holdings`);
  const total = rows.reduce((s, r) => s + r.value, 0);
  const tbody = document.querySelector('#holdings tbody');
  tbody.innerHTML = rows.map(r => {
    const weight = total > 0 ? r.value / total : 0;
    return `
    <tr>
      <td>
        ${r.name || r.ticker}
        <div class="sub">${r.ticker}</div>
      </td>
      <td>${r.quantity}</td>
      <td>${fmt(r.avg_price)}</td>
      <td>${r.current_price != null ? fmt(r.current_price) : '—'}</td>
      <td>${fmtInt(r.value)}</td>
      <td>${pctNum(weight)}</td>
      <td class="${r.pnl>=0?'pos':'neg'}">${signed(r.pnl)}</td>
      <td><span class="pill ${r.pct_return>=0?'pos':'neg'}">${pctStr(r.pct_return)}</span></td>
    </tr>`;
  }).join('');
}

async function loadPie() {
  const rows = await get(`/api/accounts/${ACCOUNT_ID}/weights`);
  const labels = rows.map(r => r.name || r.ticker);
  const data = rows.map(r => r.weight);
  const ctx = document.getElementById('pie').getContext('2d');
  if (pieChart) pieChart.destroy();
  pieChart = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data }] },
    options: {
      plugins: {
        legend: { position: 'right', labels: { boxWidth: 12, font: { size: 12 } } },
        tooltip: { callbacks: { label: c => `${c.label}  ${(c.parsed * 100).toFixed(1)}%` } },
      },
    },
  });
}

async function loadHistory() {
  const from = new Date(Date.now() - 365 * 24 * 3600 * 1000).toISOString().slice(0, 10);
  const bench = await get(`/api/accounts/${ACCOUNT_ID}/benchmark?from=${from}`);
  const allDates = Array.from(new Set([
    ...bench.portfolio.map(p => p.date),
    ...bench.benchmark.map(p => p.date),
  ])).sort();
  const portMap = Object.fromEntries(bench.portfolio.map(p => [p.date, p.value]));
  const benchMap = Object.fromEntries(bench.benchmark.map(p => [p.date, p.value]));
  const ctx = document.getElementById('history').getContext('2d');
  if (histChart) histChart.destroy();
  histChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: allDates,
      datasets: [
        {
          label: '포트폴리오',
          data: allDates.map(d => portMap[d] ?? null),
          spanGaps: true,
          borderColor: '#2563eb',
          backgroundColor: 'rgba(37, 99, 235, 0.08)',
          fill: true,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: bench.benchmark_name || bench.benchmark_ticker,
          data: allDates.map(d => benchMap[d] ?? null),
          spanGaps: true,
          borderColor: '#94a3b8',
          borderDash: [4, 4],
          pointRadius: 0,
          borderWidth: 1.5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 2.4,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 18, font: { size: 12 } } },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${(c.parsed.y).toFixed(3)}` } },
      },
      scales: {
        x: { ticks: { maxTicksLimit: 6, autoSkip: true, font: { size: 11 } }, grid: { display: false } },
        y: { ticks: { font: { size: 11 } }, grid: { color: 'rgba(148,163,184,0.15)' } },
      },
    },
  });
}

async function loadRealizedDiv() {
  const [r, d] = await Promise.all([
    get(`/api/accounts/${ACCOUNT_ID}/realized`),
    get(`/api/accounts/${ACCOUNT_ID}/dividends`),
  ]);
  const realEl = document.getElementById('realized');
  realEl.textContent = signed(r.realized);
  realEl.className = r.realized >= 0 ? 'pos' : 'neg';
  document.getElementById('dividend').textContent = fmtInt(d.total);
}

async function loadTrades() {
  const rows = await get(`/api/accounts/${ACCOUNT_ID}/trades?limit=20`);
  document.querySelector('#trades tbody').innerHTML = rows.map(t => `
    <tr>
      <td>${t.executed_at}</td>
      <td>${t.name || t.ticker}<div class="sub">${t.ticker}</div></td>
      <td><span class="pill ${t.side==='buy'?'pos':'neg'}">${t.side}</span></td>
      <td>${t.quantity}</td>
      <td>${fmt(t.price)}</td>
    </tr>`).join('');
}

async function loadAll() {
  await Promise.all([
    loadHeader(), loadHoldings(), loadPie(),
    loadHistory(), loadRealizedDiv(), loadTrades(),
  ]);
}
loadAll();
setInterval(loadAll, 15 * 60 * 1000);
