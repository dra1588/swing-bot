"""Daily OHLC loader: free source, split and dividend adjusted, cached with provenance, fails loudly."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE = "yahoo-via-yfinance auto_adjust=True (split and dividend adjusted OHLC)"
COLUMNS = ["open", "high", "low", "close"]
MAX_GAP_BUSINESS_DAYS = 5  # longer than any exchange holiday run, so a gap this size is missing data


class DataError(RuntimeError):
    pass


def validate_bars(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Return a clean copy or raise DataError. Never fills, interpolates or drops bad rows silently."""
    if df is None or df.empty:
        raise DataError(f"{symbol}: no data")
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise DataError(f"{symbol}: missing columns {missing}")
    out = df[COLUMNS].astype(float).copy()
    out.index = pd.DatetimeIndex(out.index).tz_localize(None).normalize()
    if out.index.has_duplicates:
        raise DataError(f"{symbol}: duplicate dates")
    if not out.index.is_monotonic_increasing:
        raise DataError(f"{symbol}: dates not sorted")
    if out.isna().any().any():
        raise DataError(f"{symbol}: NaN prices on {list(out.index[out.isna().any(axis=1)][:3])}")
    if (out <= 0).any().any():
        raise DataError(f"{symbol}: non-positive price")
    if ((out["high"] < out["low"]) | (out["high"] < out[["open", "close"]].max(axis=1) - 1e-9)
            | (out["low"] > out[["open", "close"]].min(axis=1) + 1e-9)).any():
        raise DataError(f"{symbol}: inconsistent OHLC")
    gaps = np.busday_count(out.index.values[:-1].astype("datetime64[D]"),
                           out.index.values[1:].astype("datetime64[D]"))
    if len(gaps) and gaps.max() > MAX_GAP_BUSINESS_DAYS:
        at = out.index[1:][gaps.argmax()]
        raise DataError(f"{symbol}: gap of {int(gaps.max())} business days ending {at.date()}")
    return out


def fetch_yahoo(symbols, start, end):
    import yfinance as yf  # imported lazily so tests and the engine need no network
    frames = {}
    for s in symbols:
        raw = yf.download(s, start=start, end=end, auto_adjust=True, progress=False, multi_level_index=False)
        raw.columns = [str(c).lower() for c in raw.columns]
        frames[s] = validate_bars(raw, s)
    return frames


def _digest(frames: dict) -> str:
    h = hashlib.sha256()
    for s in sorted(frames):
        # fixed precision, so a CSV round trip of an unchanged cache hashes identically
        h.update(s.encode()); h.update(frames[s].to_csv(float_format="%.8f").encode())
    return h.hexdigest()


def load(symbols, start, end, cache_dir="data", refresh=False, fetcher=fetch_yahoo):
    """Cached load. Writes <cache_dir>/bars.csv.gz and meta.json (source, fetched_at, sha256, window)."""
    cache = Path(cache_dir); cache.mkdir(parents=True, exist_ok=True)
    csv, meta_path = cache / "bars.csv.gz", cache / "meta.json"
    want = {"symbols": sorted(symbols), "start": str(start), "end": str(end)}
    if csv.exists() and meta_path.exists() and not refresh:
        meta = json.loads(meta_path.read_text())
        if all(meta.get(k) == v for k, v in want.items()):
            wide = pd.read_csv(csv, header=[0, 1], index_col=0, parse_dates=True)
            frames = {s: validate_bars(wide[s], s) for s in symbols}
            if _digest(frames) != meta["sha256"]:
                raise DataError("cached data does not match its recorded checksum")
            return frames, meta
    frames = {k: v.round(8) for k, v in fetcher(symbols, start, end).items()}
    pd.concat(frames, axis=1).to_csv(csv, float_format="%.8f")
    meta = {**want, "source": SOURCE, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sha256": _digest(frames), "rows": {s: len(f) for s, f in frames.items()}}
    meta_path.write_text(json.dumps(meta, indent=2))
    return frames, meta
