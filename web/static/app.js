const fmt = (n, cur = CURRENCY) =>
  new Intl.NumberFormat('ko-KR',
    { style: 'currency', currency: cur, maximumFractionDigits: 2 }).format(n);
const pct = n => (n * 100).toFixed(2) + '%';
const signed = n => new Intl.NumberFormat('ko-KR',
  { style: 'currency', currency: CURRENCY, signDisplay: 'always' }).format(n);

let pieChart = null;
let histChart = null;

async function get(path) { return (await fetch(path)).json(); }

async function loadHeader() {
  const s = await get('/api/summary');
  const row = s.accounts.find(a => a.account_id === ACCOUNT_ID);
  if (!row) return;
  document.getElementById('header-cards').innerHTML = `
    <div class="card">
      <div class="kv"><span>평가</span><strong>${fmt(row.value)}</strong></div>
      <div class="kv"><span>원가</span><strong>${fmt(row.cost)}</strong></div>
      <div class="kv"><span>수익률</span>
        <strong class="${row.pct_return>=0?'pos':'neg'}">${pct(row.pct_return)}</strong>
      </div>
      <div class="kv"><span>평가손익</span>
        <strong class="${row.pnl>=0?'pos':'neg'}">${signed(row.pnl)}</strong>
      </div>
    </div>`;
}

async function loadHoldings() {
  const rows = await get(`/api/accounts/${ACCOUNT_ID}/holdings`);
  const tbody = document.querySelector('#holdings tbody');
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.ticker}</td>
      <td>${r.quantity}</td>
      <td>${fmt(r.avg_price)}</td>
      <td>${r.current_price != null ? fmt(r.current_price) : '—'}</td>
      <td>${fmt(r.value)}</td>
      <td class="${r.pnl>=0?'pos':'neg'}">${signed(r.pnl)}</td>
      <td class="${r.pct_return>=0?'pos':'neg'}">${pct(r.pct_return)}</td>
    </tr>`).join('');
}

async function loadPie() {
  const rows = await get(`/api/accounts/${ACCOUNT_ID}/weights`);
  const labels = rows.map(r => r.ticker);
  const data = rows.map(r => r.weight);
  const ctx = document.getElementById('pie').getContext('2d');
  if (pieChart) pieChart.destroy();
  pieChart = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data }] },
    options: { plugins: { legend: { position: 'right' } } },
  });
}

async function loadHistory() {
  const bench = await get(`/api/accounts/${ACCOUNT_ID}/benchmark`);
  const ctx = document.getElementById('history').getContext('2d');
  if (histChart) histChart.destroy();
  histChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: bench.portfolio.map(p => p.date),
      datasets: [
        { label: '포트폴리오', data: bench.portfolio.map(p => p.value) },
        { label: bench.benchmark_ticker, data: bench.benchmark.map(p => p.value) },
      ],
    },
    options: { responsive: true, interaction: { intersect: false, mode: 'index' } },
  });
}

async function loadRealizedDiv() {
  const [r, d] = await Promise.all([
    get(`/api/accounts/${ACCOUNT_ID}/realized`),
    get(`/api/accounts/${ACCOUNT_ID}/dividends`),
  ]);
  document.getElementById('realized').textContent = signed(r.realized);
  document.getElementById('dividend').textContent = fmt(d.total);
}

async function loadTrades() {
  const rows = await get(`/api/accounts/${ACCOUNT_ID}/trades?limit=20`);
  document.querySelector('#trades tbody').innerHTML = rows.map(t => `
    <tr>
      <td>${t.executed_at}</td><td>${t.ticker}</td>
      <td>${t.side}</td><td>${t.quantity}</td><td>${fmt(t.price)}</td>
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
