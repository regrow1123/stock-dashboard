from __future__ import annotations

_SUFFIX_FOR_MARKET = {
    "KOSPI": ".KS",
    "KOSDAQ": ".KQ",
    "KONEX": ".KN",
}


class KrxCache:
    """In-memory KRX ticker mapping with name search."""

    def __init__(self) -> None:
        # name -> list[(ticker_with_suffix, market)]
        self._by_name: dict[str, list[tuple[str, str]]] = {}
        # ticker -> name
        self._by_ticker: dict[str, str] = {}

    def _load_from_records(self, records: list[dict]) -> None:
        self._by_name.clear()
        self._by_ticker.clear()
        for r in records:
            market = r.get("Market") or ""
            suffix = _SUFFIX_FOR_MARKET.get(market)
            if suffix is None:
                continue
            ticker = f"{r['Code']}{suffix}"
            name = r["Name"]
            self._by_name.setdefault(name, []).append((ticker, market))
            self._by_ticker[ticker] = name

    def search_by_name(self, name: str) -> list[tuple[str, str]]:
        exact = self._by_name.get(name)
        if exact:
            return list(exact)
        # Substring fallback: any name containing the query
        out: list[tuple[str, str]] = []
        for n, items in self._by_name.items():
            if name in n:
                out.extend(items)
        return out

    def get_name(self, ticker: str) -> str | None:
        return self._by_ticker.get(ticker)
