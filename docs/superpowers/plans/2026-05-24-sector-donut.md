# 계좌별 섹터 도넛 차트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 각 계좌 페이지 최상단에 보유 종목의 섹터별 비중을 CSS conic-gradient 도넛 + 범례로 표시한다.

**Architecture:** `Instrument`에 `sector` 컬럼 추가(yfinance로 자동 조회·저장), `GET /api/accounts/{id}/sectors`가 보유 종목을 섹터별 value로 합산, 프론트는 의존성 없이 conic-gradient 도넛을 렌더.

**Tech Stack:** FastAPI, SQLAlchemy 2.0(SQLite), yfinance, vanilla JS, Tailwind v4. Chart.js 미사용.

**Spec:** `docs/superpowers/specs/2026-05-24-sector-donut-design.md`

**Conventions:**
- 응답은 한국어, 코드 주석은 영어, 커밋은 conventional commits.
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` 추가.
- 테스트는 절대 실제 네트워크를 치지 않는다. yfinance는 `monkeypatch.setattr("app.sectors.yf", ...)`로 모킹.
- 테스트 실행: `.venv/bin/pytest -q`.

---

### Task 1: `Instrument.sector` 컬럼 + SQLite 마이그레이션 가드

**Files:**
- Modify: `app/models.py` (Instrument 클래스, line ~105-108)
- Modify: `app/db.py:init_db` (line ~19-22)
- Test: `tests/test_db.py` (신규)

- [ ] **Step 1: 마이그레이션 가드 실패 테스트 작성**

`tests/test_db.py` 생성:

```python
from sqlalchemy import create_engine

from app.db import init_db


def test_init_db_adds_sector_column_to_existing_instruments(tmp_path):
    # Simulate a pre-existing DB whose instruments table lacks `sector`.
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE instruments (ticker VARCHAR PRIMARY KEY, name VARCHAR)"
        )
        conn.exec_driver_sql(
            "INSERT INTO instruments (ticker, name) VALUES ('AAPL', 'Apple')"
        )
    # init_db must add the missing column without dropping data.
    init_db(engine)
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql(
            "PRAGMA table_info(instruments)").fetchall()}
        assert "sector" in cols
        row = conn.exec_driver_sql(
            "SELECT name FROM instruments WHERE ticker='AAPL'").fetchone()
        assert row[0] == "Apple"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: FAIL — `sector`가 컬럼에 없음 (AssertionError).

- [ ] **Step 3: 모델 컬럼 추가**

`app/models.py`의 Instrument 클래스에 컬럼 추가:

```python
class Instrument(Base):
    __tablename__ = "instruments"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: init_db 마이그레이션 가드 추가**

`app/db.py`를 다음과 같이 수정:

```python
def _ensure_sqlite_columns(engine) -> None:
    # create_all won't ALTER existing tables; add missing columns by hand.
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql(
            "PRAGMA table_info(instruments)").fetchall()}
        if "sector" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE instruments ADD COLUMN sector VARCHAR")


def init_db(engine) -> None:
    # Import models so their tables are registered on Base.metadata
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    _ensure_sqlite_columns(engine)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add app/models.py app/db.py tests/test_db.py
git commit -m "feat(models): add Instrument.sector column with sqlite migration guard

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `app/sectors.py` — yfinance 섹터 조회 + 한글 매핑

**Files:**
- Create: `app/sectors.py`
- Test: `tests/test_sectors.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_sectors.py` 생성:

```python
from app import sectors


class _FakeTicker:
    def __init__(self, info):
        self._info = info

    @property
    def info(self):
        return self._info


def _fake_yf(info):
    class _YF:
        def Ticker(self, ticker):
            return _FakeTicker(info)
    return _YF()


def test_fetch_sector_maps_gics_to_korean(monkeypatch):
    monkeypatch.setattr(sectors, "yf", _fake_yf({"sector": "Technology"}))
    assert sectors.fetch_sector("AAPL") == "정보기술"


def test_fetch_sector_passes_through_unknown_sector(monkeypatch):
    monkeypatch.setattr(sectors, "yf", _fake_yf({"sector": "Conglomerates"}))
    assert sectors.fetch_sector("X") == "Conglomerates"


def test_fetch_sector_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(sectors, "yf", _fake_yf({}))
    assert sectors.fetch_sector("ZZZ") is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_sectors.py -v`
Expected: FAIL — `ModuleNotFoundError: app.sectors`.

- [ ] **Step 3: 모듈 구현**

`app/sectors.py` 생성:

```python
import yfinance as yf

# GICS sector (yfinance English) -> Korean display label.
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
    """Look up a ticker's GICS sector via yfinance, mapped to Korean.

    Returns None when yfinance has no sector for the ticker. Unknown English
    sectors (not in GICS_KR) are passed through unchanged.
    """
    info = yf.Ticker(ticker).info
    raw = info.get("sector")
    if not raw:
        return None
    return GICS_KR.get(raw, raw)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_sectors.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 커밋**

```bash
git add app/sectors.py tests/test_sectors.py
git commit -m "feat(sectors): yfinance sector lookup with GICS korean mapping

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: `register_instrument`에서 신규 종목 섹터 자동 저장

**Files:**
- Modify: `app/mcp_server.py:register_instrument` (line ~161-168)
- Test: `tests/test_mcp_server.py` (기존 파일에 추가; 없으면 신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_mcp_server.py`에 추가 (없으면 파일 생성, import는 파일 상단에 맞춰 조정):

```python
def test_register_instrument_saves_sector(db, monkeypatch):
    import app.mcp_server as mcp
    from app.models import Instrument

    monkeypatch.setattr("app.sectors.fetch_sector", lambda t: "정보기술")
    mcp.register_instrument(db, ticker="AAPL", name="Apple")

    inst = db.get(Instrument, "AAPL")
    assert inst.sector == "정보기술"


def test_register_instrument_tolerates_sector_failure(db, monkeypatch):
    import app.mcp_server as mcp
    from app.models import Instrument

    def _boom(t):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.sectors.fetch_sector", _boom)
    # Registration must still succeed even if sector lookup fails.
    mcp.register_instrument(db, ticker="MSFT", name="Microsoft")

    inst = db.get(Instrument, "MSFT")
    assert inst is not None
    assert inst.sector is None
```

> NOTE: `db` fixture는 `tests/conftest.py` 제공. 기존 `tests/test_mcp_server.py`가 있으면 그 import 스타일을 따른다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_mcp_server.py -k register_instrument_saves_sector -v`
Expected: FAIL — `inst.sector`가 None.

- [ ] **Step 3: register_instrument 수정**

`app/mcp_server.py`:

```python
def register_instrument(db: Session, ticker: str, name: str) -> dict[str, Any]:
    from app.sectors import fetch_sector

    inst = db.get(Instrument, ticker)
    if inst is None:
        sector = None
        try:
            sector = fetch_sector(ticker)
        except Exception:
            sector = None  # best-effort; registration must not fail
        db.add(Instrument(ticker=ticker, name=name, sector=sector))
    else:
        inst.name = name
    db.commit()
    return {"ok": True, "ticker": ticker, "name": name}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_mcp_server.py -k register_instrument -v`
Expected: PASS (2개)

- [ ] **Step 5: 커밋**

```bash
git add app/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): fetch sector on new instrument registration

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: CLI `backfill-sectors` — 기존 종목 일괄 채우기

**Files:**
- Modify: `app/cli.py` (cmd 함수 추가 + 서브파서 + dispatch)
- Test: `tests/test_cli.py` (기존 파일에 추가; 없으면 신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_cli.py`에 추가:

```python
def test_backfill_sectors_fills_only_null(db, monkeypatch):
    from app.cli import cmd_backfill_sectors
    from app.models import Instrument

    db.add_all([
        Instrument(ticker="AAPL", name="Apple", sector=None),
        Instrument(ticker="MSFT", name="Microsoft", sector="정보기술"),
        Instrument(ticker="ZZZ", name="Unknown", sector=None),
    ])
    db.commit()

    # AAPL resolves; ZZZ has no sector and is left untouched.
    lookup = {"AAPL": "정보기술", "ZZZ": None}
    monkeypatch.setattr("app.cli.fetch_sector", lambda t: lookup.get(t))

    cmd_backfill_sectors(session=db)

    assert db.get(Instrument, "AAPL").sector == "정보기술"
    assert db.get(Instrument, "MSFT").sector == "정보기술"  # untouched
    assert db.get(Instrument, "ZZZ").sector is None  # still null, retry later
```

> NOTE: `db` fixture가 `tests/conftest.py`에 있음. 기존 `tests/test_cli.py` 스타일 확인.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_cli.py -k backfill_sectors -v`
Expected: FAIL — `ImportError: cannot import name 'cmd_backfill_sectors'`.

- [ ] **Step 3: CLI 구현**

`app/cli.py` 상단 import에 추가:

```python
from app.models import Account, Instrument
from app.sectors import fetch_sector
```

(`Account`는 이미 import됨 — `Instrument`만 추가, `fetch_sector` 추가.)

cmd 함수 추가:

```python
def cmd_backfill_sectors(*, session: Session) -> None:
    pending = session.query(Instrument).filter(Instrument.sector.is_(None)).all()
    for inst in pending:
        sector = fetch_sector(inst.ticker)
        if sector:
            inst.sector = sector
    session.commit()
```

`main()`의 서브파서 등록부에 추가 (다른 add_parser 뒤):

```python
    sub.add_parser("backfill-sectors")
```

dispatch에 추가 (`elif args.cmd == "backfill-prices":` 블록 뒤):

```python
        elif args.cmd == "backfill-sectors":
            cmd_backfill_sectors(session=session)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_cli.py -k backfill_sectors -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/cli.py tests/test_cli.py
git commit -m "feat(cli): add backfill-sectors command

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: `GET /api/accounts/{id}/sectors` 엔드포인트

**Files:**
- Modify: `app/api.py` (새 라우트 추가; `Instrument`는 이미 import됨)
- Test: `tests/test_api.py` (추가)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_api.py`에 추가:

```python
def test_sectors_endpoint(db, engine, monkeypatch):
    from app.models import Account, Instrument, LivePrice, SeedHolding
    db.add_all([
        Account(id="a", name="ISA", broker="B", currency="KRW", display_order=1),
        # tech: 005930 value=10*84000=840000
        SeedHolding(account_id="a", ticker="005930.KS", quantity=10, avg_price=70000),
        # tech: 000660 value=2*180000=360000
        SeedHolding(account_id="a", ticker="000660.KS", quantity=2, avg_price=150000),
        # finance: 105560 value=5*60000=300000
        SeedHolding(account_id="a", ticker="105560.KS", quantity=5, avg_price=50000),
        # no Instrument row -> 미분류: 030200 value=1*100000=100000
        SeedHolding(account_id="a", ticker="030200.KS", quantity=1, avg_price=90000),
        Instrument(ticker="005930.KS", name="삼성전자", sector="정보기술"),
        Instrument(ticker="000660.KS", name="SK하이닉스", sector="정보기술"),
        Instrument(ticker="105560.KS", name="KB금융", sector="금융"),
    ])
    db.add_all([
        LivePrice(ticker="005930.KS", price=84000, currency="KRW",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
        LivePrice(ticker="000660.KS", price=180000, currency="KRW",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
        LivePrice(ticker="105560.KS", price=60000, currency="KRW",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
        LivePrice(ticker="030200.KS", price=100000, currency="KRW",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
    ])
    db.commit()
    app = _app_with_engine(engine, monkeypatch)
    c = TestClient(app)
    r = c.get("/api/accounts/a/sectors")
    assert r.status_code == 200
    payload = r.json()
    assert payload["currency"] == "KRW"
    items = payload["items"]
    # tech 1,200,000 / finance 300,000 / 미분류 100,000 ; total 1,600,000
    assert [it["sector"] for it in items] == ["정보기술", "금융", "미분류"]
    assert items[0]["value"] == 1_200_000
    assert round(items[0]["weight"], 4) == round(1_200_000 / 1_600_000, 4)
    assert items[2]["sector"] == "미분류"
    assert items[2]["value"] == 100_000
    # 404 for unknown account
    assert c.get("/api/accounts/nope/sectors").status_code == 404
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_api.py -k sectors_endpoint -v`
Expected: FAIL — 404 (라우트 없음).

- [ ] **Step 3: 라우트 구현**

`app/api.py`에 추가 (예: `account_holdings` 근처):

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
        i = inst.get(r["ticker"])
        sec = (i.sector if i else None) or "미분류"
        agg[sec] = agg.get(sec, 0.0) + r["value"]
    total = sum(agg.values()) or 1.0
    items = sorted(
        ({"sector": s, "value": v, "weight": v / total} for s, v in agg.items()),
        key=lambda x: x["value"], reverse=True,
    )
    return {"currency": acc.currency, "items": items}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_api.py -k sectors_endpoint -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat(api): add per-account sector breakdown endpoint

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: 프론트엔드 — 도넛 섹션 + 렌더 함수 + CSS

**Files:**
- Modify: `web/templates/account.html` (계좌 태그 div 아래, weights section 위)
- Modify: `web/static/app.js` (`renderAccount`에 호출 추가 + `renderAccountSectors`)
- Modify: `web/styles.src.css` (또는 컴포넌트 CSS 위치) — `.sector-*` 스타일

- [ ] **Step 1: 템플릿에 섹션 추가**

`web/templates/account.html`에서 계좌 정보 div(`<div class="mt-1 mb-3 ...">...</div>`)와 `<section aria-labelledby="weights-heading">` 사이에 삽입:

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

- [ ] **Step 2: app.js — renderAccount에 호출 추가**

`renderAccount()`의 `Promise.all` 배열 **맨 앞**에 `renderAccountSectors()` 추가:

```javascript
async function renderAccount() {
  await Promise.all([
    renderAccountSectors(),
    renderAccountWeights(),
    renderAccountHoldings(),
    renderAccountPostSells(),
    renderAccountTrades(),
  ]);
}
```

- [ ] **Step 3: app.js — renderAccountSectors 구현**

`renderAccountPostSells` 근처에 추가:

```javascript
const SECTOR_COLORS = [
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
    <div class="sector-donut" role="img" aria-label="섹터 비중 도넛 차트"
         style="background: conic-gradient(${stops})"></div>
    <ul class="sector-legend">${legend}</ul>`;
}
```

- [ ] **Step 4: CSS 추가**

`web/styles.src.css`에 추가 (기존 `weight-list` 등 컴포넌트 근처):

```css
.sector-chart {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}
@media (min-width: 768px) {
  .sector-chart { flex-direction: row; align-items: center; }
}
.sector-donut {
  width: 9rem;
  height: 9rem;
  border-radius: 50%;
  flex-shrink: 0;
  /* punch a hole to make it a donut */
  -webkit-mask: radial-gradient(circle, transparent 52%, #000 53%);
  mask: radial-gradient(circle, transparent 52%, #000 53%);
}
.sector-legend {
  list-style: none;
  margin: 0;
  padding: 0;
  flex: 1;
  width: 100%;
}
.sector-legend-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0;
  font-size: 0.875rem;
}
.sector-dot {
  width: 0.75rem;
  height: 0.75rem;
  border-radius: 50%;
  flex-shrink: 0;
}
.sector-name { flex: 1; }
.sector-weight {
  font-variant-numeric: tabular-nums;
  color: var(--color-muted);
}
```

- [ ] **Step 5: CSS 빌드**

Run: `npm run build:css`
Expected: `web/static/styles.css` 재생성, 에러 없음.

> Node 미설치 환경이면 Docker 빌드 시 생성되므로 스킵 가능. 단, 로컬 브라우저 확인하려면 빌드 필요.

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `.venv/bin/pytest -q`
Expected: 전부 PASS (기존 + 신규).

- [ ] **Step 7: 커밋**

```bash
git add web/templates/account.html web/static/app.js web/styles.src.css web/static/styles.css
git commit -m "feat(web): per-account sector donut at top of account page

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: 통합 검증 (Docker + 브라우저)

**Files:** 없음 (검증만)

- [ ] **Step 1: 이미지 재빌드 & 재기동**

```bash
docker compose build app && docker compose up -d app
```

- [ ] **Step 2: 기존 종목 섹터 backfill**

```bash
docker compose exec -T app python -m app.cli backfill-sectors
```

- [ ] **Step 3: 엔드포인트 확인**

```bash
curl -s http://localhost:8090/api/accounts/samsung_isa/sectors | python -m json.tool
```
Expected: `currency`/`items` 구조, 섹터별 합산값.

- [ ] **Step 4: 브라우저 확인 (Playwright MCP)**

`http://localhost:8090/accounts/samsung_isa` 접속 → 최상단에 '섹터 비중' 도넛 + 범례 표시 확인. 콘솔 에러 없음. 스크린샷 후 정리(rm).

- [ ] **Step 5: 푸시 (사용자 승인 후)**

```bash
git push
```

---

## Self-Review 결과

- **Spec 커버리지**: 모델 컬럼+마이그레이션(T1) / 조회·매핑(T2) / 등록 자동저장(T3) / CLI backfill(T4) / API(T5) / 프론트·CSS(T6) / 검증(T7) — spec 전 항목 매핑됨.
- **타입 일관성**: `fetch_sector`(T2) 시그니처가 T3·T4에서 동일하게 사용됨. API 응답 `{sector,value,weight}`가 T6 프론트 소비와 일치.
- **플레이스홀더**: 없음. 모든 코드 스텝에 실제 코드 포함.
- **주의**: T3/T4의 `tests/test_mcp_server.py`·`tests/test_cli.py`는 기존 파일 유무에 따라 import 스타일을 맞출 것(`db` fixture는 conftest 제공).
