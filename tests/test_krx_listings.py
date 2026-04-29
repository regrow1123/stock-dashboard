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
