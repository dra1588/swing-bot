"""Daily-bar trend following with a market filter. Pure functions: no I/O, no clock, no look-ahead.

A signal computed from bar t uses only bars up to and including t. The engine fills it at the open
of bar t+1.
"""
import numpy as np
import pandas as pd


def indicators(bars: pd.DataFrame, p) -> pd.DataFrame:
    """bars: index = dates, columns open/high/low/close. Returns bars plus sma, atr, roc."""
    out = bars.copy()
    out["sma"] = out["close"].rolling(p.trend_window).mean()
    prev_close = out["close"].shift(1)
    true_range = pd.concat([out["high"] - out["low"], (out["high"] - prev_close).abs(),
                            (out["low"] - prev_close).abs()], axis=1).max(axis=1)
    out["atr"] = true_range.rolling(p.atr_window).mean()
    out["roc"] = out["close"] / out["close"].shift(p.trend_window) - 1.0
    return out


def market_ok(market_bars: pd.DataFrame, p) -> pd.Series:
    sma = market_bars["close"].rolling(p.market_window).mean()
    return (market_bars["close"] > sma).fillna(False)


def entry_signal(row) -> bool:
    return bool(pd.notna(row["sma"]) and pd.notna(row["atr"]) and row["atr"] > 0
                and row["close"] > row["sma"])


def exit_signal(row, high_close_since_entry: float, p) -> str | None:
    """Returns the exit reason, or None. Checked on the close; filled at the next open."""
    if pd.notna(row["sma"]) and row["close"] < row["sma"]:
        return "trend_break"
    if pd.notna(row["atr"]) and row["close"] < high_close_since_entry - p.atr_mult * row["atr"]:
        return "trailing_stop"
    return None


def position_size(equity: float, price: float, atr: float, p) -> float:
    """Fractional shares: risk_pct of equity over the stop distance, capped by max_position_pct."""
    if price <= 0 or atr <= 0:
        return 0.0
    by_risk = p.risk_pct * equity / (p.atr_mult * atr)
    by_cap = p.max_position_pct * equity / price
    return float(max(0.0, min(by_risk, by_cap)))


def rank_candidates(candidates: dict) -> list:
    """Order entry candidates by 100-day return (highest first); ties break alphabetically."""
    return sorted(candidates, key=lambda s: (-float(candidates[s]["roc"]), s))
