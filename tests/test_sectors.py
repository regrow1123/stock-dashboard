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
