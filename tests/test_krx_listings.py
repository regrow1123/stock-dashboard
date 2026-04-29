import pickle
from unittest.mock import MagicMock

import pandas as pd

from app.krx_listings import KrxCache


def test_search_by_name_exact_match():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
        {"Code": "035720", "Name": "카카오", "Market": "KOSPI"},
    ])
    result = cache.search_by_name("삼성전자")
    assert result == [("005930.KS", "KOSPI")]


def test_search_by_name_kosdaq_suffix():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "380550", "Name": "뉴로핏", "Market": "KOSDAQ"},
    ])
    result = cache.search_by_name("뉴로핏")
    assert result == [("380550.KQ", "KOSDAQ")]


def test_search_by_name_no_match():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
    ])
    assert cache.search_by_name("존재하지않는회사") == []


def test_search_by_name_falls_back_to_substring():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
        {"Code": "005935", "Name": "삼성전자우", "Market": "KOSPI"},
    ])
    # exact match wins — only "삼성전자"
    assert cache.search_by_name("삼성전자") == [("005930.KS", "KOSPI")]
    # substring fallback when no exact match — "삼성" returns both
    out = cache.search_by_name("삼성")
    out_set = {t for t, _ in out}
    assert out_set == {"005930.KS", "005935.KS"}


def test_get_name_returns_canonical_korean_name():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
    ])
    assert cache.get_name("005930.KS") == "삼성전자"
    assert cache.get_name("999999.KS") is None


def test_refresh_calls_fdr_and_loads_records(monkeypatch, tmp_path):
    df = pd.DataFrame([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
        {"Code": "380550", "Name": "뉴로핏", "Market": "KOSDAQ"},
    ])
    fake_fdr = MagicMock()
    fake_fdr.StockListing.return_value = df
    monkeypatch.setattr("app.krx_listings.fdr", fake_fdr)

    cache = KrxCache(persist_path=tmp_path / "krx.pkl")
    n = cache.refresh()

    assert n == 2
    fake_fdr.StockListing.assert_called_once_with("KRX")
    assert cache.search_by_name("삼성전자") == [("005930.KS", "KOSPI")]
    assert cache.search_by_name("뉴로핏") == [("380550.KQ", "KOSDAQ")]


def test_refresh_persists_to_pickle(monkeypatch, tmp_path):
    df = pd.DataFrame([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
    ])
    fake_fdr = MagicMock()
    fake_fdr.StockListing.return_value = df
    monkeypatch.setattr("app.krx_listings.fdr", fake_fdr)

    pkl = tmp_path / "krx.pkl"
    cache = KrxCache(persist_path=pkl)
    cache.refresh()

    assert pkl.exists()
    with pkl.open("rb") as f:
        loaded = pickle.load(f)
    assert "삼성전자" in loaded["by_name"]


def test_hydrate_from_pickle_skips_fdr(monkeypatch, tmp_path):
    fake_fdr = MagicMock()
    monkeypatch.setattr("app.krx_listings.fdr", fake_fdr)

    pkl = tmp_path / "krx.pkl"
    with pkl.open("wb") as f:
        pickle.dump(
            {
                "by_name": {"삼성전자": [("005930.KS", "KOSPI")]},
                "by_ticker": {"005930.KS": "삼성전자"},
            },
            f,
        )

    cache = KrxCache(persist_path=pkl)
    assert cache.hydrate() is True
    assert cache.search_by_name("삼성전자") == [("005930.KS", "KOSPI")]
    fake_fdr.StockListing.assert_not_called()


def test_hydrate_returns_false_when_no_pickle(tmp_path):
    cache = KrxCache(persist_path=tmp_path / "missing.pkl")
    assert cache.hydrate() is False
