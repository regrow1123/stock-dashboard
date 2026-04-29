from __future__ import annotations

import pickle
from pathlib import Path

import FinanceDataReader as fdr  # noqa: N813

_SUFFIX_FOR_MARKET = {
    "KOSPI": ".KS",
    "KOSDAQ": ".KQ",
    "KONEX": ".KN",
}


class KrxCache:
    """KRX ticker mapping backed by FinanceDataReader, with pickle persistence."""

    def __init__(self, persist_path: Path | None = None) -> None:
        # name -> list[(ticker_with_suffix, market)]
        self._by_name: dict[str, list[tuple[str, str]]] = {}
        # ticker -> name
        self._by_ticker: dict[str, str] = {}
        self.persist_path = persist_path

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

    def refresh(self) -> int:
        """Pull KRX listings from FDR. Returns count of usable rows loaded."""
        df = fdr.StockListing("KRX")
        records = df.to_dict("records")
        self._load_from_records(records)
        if self.persist_path is not None:
            self._persist()
        return len(self._by_ticker)

    def _persist(self) -> None:
        assert self.persist_path is not None
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        with self.persist_path.open("wb") as f:
            pickle.dump(
                {"by_name": self._by_name, "by_ticker": self._by_ticker}, f
            )

    def hydrate(self) -> bool:
        """Load cache from pickle. Return True on success, False if missing/corrupt."""
        if self.persist_path is None or not self.persist_path.exists():
            return False
        try:
            with self.persist_path.open("rb") as f:
                data = pickle.load(f)
            self._by_name = data["by_name"]
            self._by_ticker = data["by_ticker"]
            return True
        except (pickle.PickleError, KeyError, EOFError):
            return False


# Module-level singleton wired by main.py / scheduler at startup.
_default_cache: KrxCache | None = None


def get_cache() -> KrxCache:
    global _default_cache
    if _default_cache is None:
        from app.config import get_settings

        settings = get_settings()
        pkl = settings.db_path.parent / "krx_cache.pkl"
        _default_cache = KrxCache(persist_path=pkl)
    return _default_cache
