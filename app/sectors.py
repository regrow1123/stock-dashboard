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
