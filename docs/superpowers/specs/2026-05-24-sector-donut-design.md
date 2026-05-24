# 계좌별 섹터 도넛 차트 — 설계

## 목표

각 계좌 페이지 최상단에, 그 계좌가 보유한 종목들의 **섹터별 비중**을 CSS
`conic-gradient` 도넛 + HTML 범례로 보여준다. 통화가 단일이므로 value 합산이
안전하다.

## 비목표 (YAGNI)

- 전체(메인) 포트폴리오 합산 차트 — 통화 혼합 문제로 제외
- Chart.js 재도입 — 직전 커밋에서 제거함, CSS만 사용
- 섹터 자동 새로고침 스케줄러 잡 — 섹터는 거의 안 바뀜, CLI backfill로 충분
- 산업(industry) 세분류 — 섹터(GICS 11개)까지만

## 데이터 모델

`app/models.py:Instrument`에 컬럼 추가:

```python
sector: Mapped[str | None] = mapped_column(String, nullable=True)
```

마이그레이션: 이 프로젝트는 Alembic 없이 `Base.metadata.create_all`만 쓴다.
신규/테스트 DB는 그대로 생성되지만, **기존 prod SQLite의 `instruments` 테이블엔
컬럼이 자동 추가되지 않는다.** `app/db.py:init_db`에 idempotent 가드 추가:

```python
def _ensure_sqlite_columns(engine) -> None:
    # create_all won't ALTER existing tables; add missing columns by hand.
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql(
            "PRAGMA table_info(instruments)").fetchall()}
        if "sector" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE instruments ADD COLUMN sector VARCHAR")
```

`init_db`에서 `create_all` 직후 호출. SQLite 전용 (프로젝트는 SQLite만 사용).

## 섹터 조회 — `app/sectors.py` (신규)

```python
GICS_KR = {
    "Technology": "정보기술",
    "Financial Services": "금융",
    "Healthcare": "헬스케어",
    "Consumer Cyclical": "경기소비재",
    "Consumer Defensive": "필수소비재",
    "Industrials": "산업재",
    "Energy": "에너지",
    "Basic Materials": "소재",
    "Communication Services": "커뮤니케이션",
    "Utilities": "유틸리티",
    "Real Estate": "부동산",
}
UNCLASSIFIED = "미분류"

def fetch_sector(ticker: str) -> str | None:
    # Returns Korean GICS label, or None if yfinance has no sector.
    info = yf.Ticker(ticker).info
    raw = info.get("sector")
    if not raw:
        return None
    return GICS_KR.get(raw, raw)  # unknown English sector passed through
```

- yfinance를 모듈 레벨 `import yfinance as yf`로 두어 테스트에서
  `monkeypatch.setattr("app.sectors.yf", ...)` 가능하게 한다.
- 매핑에 없는 영문 섹터는 원문 그대로 통과 (드물지만 깨지지 않게).

### 호출 지점

1. **신규 등록**: `app/mcp_server.py:register_instrument`에서 새
   `Instrument` 생성 시 `sector=fetch_sector(ticker)` 저장. 네트워크 실패는
   삼켜서 `None`으로 둔다(등록 자체는 성공해야 함).
2. **기존 종목 backfill**: CLI `backfill-sectors` — `sector IS NULL`인
   Instrument에 대해 `fetch_sector` 호출 후 저장. 결과 None이면 건너뜀
   (다음 실행 때 재시도 가능).

## API — `GET /api/accounts/{id}/sectors`

`app/api.py`. `_holdings_for(db, account_id)` 결과를 재사용해 섹터별 value 합산.

```python
@router.get("/accounts/{account_id}/sectors")
def account_sectors(account_id: str, db: Session = Depends(get_db)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404)
    rows = _holdings_for(db, account_id)
    inst = {i.ticker: i for i in db.query(Instrument).all()}
    agg: dict[str, float] = {}
    for r in rows:
        sec = (inst.get(r["ticker"]).sector if inst.get(r["ticker"]) else None) \
              or "미분류"
        agg[sec] = agg.get(sec, 0.0) + r["value"]
    total = sum(agg.values()) or 1.0
    items = sorted(
        ({"sector": s, "value": v, "weight": v / total} for s, v in agg.items()),
        key=lambda x: x["value"], reverse=True,
    )
    return {"currency": acc.currency, "items": items}
```

응답 예:
```json
{"currency":"KRW","items":[
  {"sector":"정보기술","value":12345.0,"weight":0.42},
  {"sector":"미분류","value":2000.0,"weight":0.07}
]}
```

## 프론트엔드

### `web/templates/account.html`

계좌 정보 태그(`<div class="mt-1 mb-3 ...">`) 아래, '종목 비중'
`<section>` **위**에 삽입:

```html
<section aria-labelledby="sectors-heading">
  <div class="section-heading">
    <h2 id="sectors-heading">섹터 비중</h2>
  </div>
  <div class="card card-body">
    <div id="sectors" class="sector-chart" aria-busy="true">
      <div class="skeleton" style="height: 9rem"></div>
    </div>
  </div>
</section>
```

### `web/static/app.js`

`renderAccount()`의 `Promise.all`에 `renderAccountSectors()` 추가 (최상단이므로
배열 첫 항목).

```javascript
const SECTOR_COLORS = [
  // fixed sequence; cycles if >N sectors
  '#5b8def', '#34c759', '#ff9f0a', '#ff453a', '#bf5af2',
  '#5ac8fa', '#ffd60a', '#ff6482', '#64d2ff', '#30d158', '#8e8e93',
];

async function renderAccountSectors() {
  const host = document.getElementById('sectors');
  if (!host) return;
  let data;
  try { data = await getJSON(`/api/accounts/${window.ACCOUNT_ID}/sectors`); }
  catch (e) { host.innerHTML = ''; return; }
  const items = data.items || [];
  if (!items.length) {
    host.removeAttribute('aria-busy');
    host.innerHTML = `<div class="row-sub">보유 종목이 없습니다.</div>`;
    return;
  }
  // build conic-gradient stops
  let acc = 0;
  const stops = items.map((it, i) => {
    const c = SECTOR_COLORS[i % SECTOR_COLORS.length];
    const start = acc * 100, end = (acc + it.weight) * 100;
    acc += it.weight;
    return `${c} ${start}% ${end}%`;
  }).join(', ');
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
    <div class="sector-donut" role="img"
         aria-label="섹터 비중 도넛 차트"
         style="background: conic-gradient(${stops})"></div>
    <ul class="sector-legend">${legend}</ul>`;
}
```

- `escapeHTML`, `getJSON`은 기존 헬퍼 재사용. 비중은 부호 없이
  `(weight*100).toFixed(1)+'%'` (기존 `pctStr`은 '+' 부호를 붙여 부적합).

### CSS (`web/styles.src.css` 또는 컴포넌트 위치)

- `.sector-chart`: flex(모바일 세로, 768px↑ 가로)
- `.sector-donut`: 원형, 중앙 구멍은 `mask`/`radial-gradient`로 도넛화
- `.sector-legend` / `.sector-legend-row` / `.sector-dot`: 기존 `weight-list`
  톤 맞춤. `npm run build:css` 필요.

## 테스트

- `tests/test_api.py::test_sectors_endpoint`: 두 계좌·여러 섹터 시드,
  섹터별 합산·weight·내림차순 정렬, 미분류 폴백, 404. live price 모킹.
- `tests/test_sectors.py`: `fetch_sector` — yfinance 모킹으로 영문→한글 매핑,
  매핑에 없는 섹터 통과, sector 없음→None.
- `tests/test_cli.py`(있으면) 또는 신규: `backfill-sectors`가 NULL만 채우고
  None 결과는 건너뛰는지. yfinance 모킹.
- 기존 테스트는 in-memory DB라 `_ensure_sqlite_columns`도 자연 통과.

## 색상/접근성 메모

- conic-gradient 색은 CSS `color-mix` 아님(직전 차트 이슈와 무관, 순수 hex).
- 도넛에 `role="img"`+`aria-label`, 범례가 실질 데이터 테이블 역할.
