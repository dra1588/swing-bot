"""Frozen Phase 1 parameters. See docs/PREREGISTRATION.md. Do not tune; add a new dated version instead."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    trend_window: int = 100        # stock must close above its 100-day average
    market_window: int = 200       # SPY must close above its 200-day average
    atr_window: int = 14
    atr_mult: float = 2.0          # trailing stop distance in ATRs
    risk_pct: float = 0.01         # of equity risked per trade
    max_positions: int = 4
    max_position_pct: float = 0.20  # of equity in one name
    daily_loss_cap_pct: float = 0.02
    slippage_bps: float = 5.0      # per side
    half_spread_bps: float = 5.0   # per side, used when no quote is available
    commission: float = 0.0        # per order, account currency
    start_capital: float = 1000.0
    market_symbol: str = "SPY"


# 30 largest US stocks by market cap on 1 Jan 2020, fixed in advance, plus SPY and QQQ.
# Survivorship bias is disclosed in the preregistration: this list is as of 2020, not today.
UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "JNJ", "V", "PG",
            "UNH", "HD", "MA", "NVDA", "DIS", "BAC", "VZ", "ADBE", "CMCSA", "NFLX",
            "KO", "PFE", "INTC", "T", "MRK", "PEP", "CSCO", "WMT", "XOM", "CVX",
            "SPY", "QQQ"]
