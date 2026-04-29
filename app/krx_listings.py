from __future__ import annotations

_SUFFIX_FOR_MARKET = {
    "KOSPI": ".KS",
    "KOSDAQ": ".KQ",
    "KONEX": ".KN",
}


class KrxCache:
    """In-memory KRX ticker mapping. Exact-name resolution only (Task 3)."""

    def __init__(self) -> None:
        # name -> list[(ticker_with_suffix, market)]
        self._by_name: dict[str, list[tuple[str, str]]] = {}

    def _load_from_records(self, records: list[dict]) -> None:
        self._by_name.clear()
        for r in records:
            market = r.get("Market") or ""
            suffix = _SUFFIX_FOR_MARKET.get(market)
            if suffix is None:
                continue
            ticker = f"{r['Code']}{suffix}"
            self._by_name.setdefault(r["Name"], []).append((ticker, market))

    def search_by_name(self, name: str) -> list[tuple[str, str]]:
        return list(self._by_name.get(name, []))
