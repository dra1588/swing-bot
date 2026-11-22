"""Event-driven daily backtest with next-open fills, explicit costs and the preregistered caps."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import strategy


@dataclass
class Result:
    equity: pd.Series
    trades: list = field(default_factory=list)   # one dict per closed trade
    fills: list = field(default_factory=list)    # one dict per fill, ledger-shaped
    halted_days: int = 0


def _fill_price(open_px: float, side: str, p) -> float:
    bps = (p.slippage_bps + p.half_spread_bps) / 1e4
    return open_px * (1 + bps) if side == "BUY" else open_px * (1 - bps)


def run(data: dict, p, start=None, end=None) -> Result:
    """data: symbol -> OHLC DataFrame (same date index convention). Trades every symbol except none
    is special-cased; the market filter reads p.market_symbol."""
    ind = {s: strategy.indicators(df, p) for s, df in data.items()}
    prev = {s: df.shift(1) for s, df in ind.items()}  # signal-day values, for sizing at the next open
    mkt_ok = strategy.market_ok(data[p.market_symbol], p)
    dates = sorted(set().union(*[set(df.index) for df in data.values()]))
    if start is not None:
        dates = [d for d in dates if d >= pd.Timestamp(start)]
    if end is not None:
        dates = [d for d in dates if d <= pd.Timestamp(end)]

    cash = p.start_capital
    positions: dict = {}          # symbol -> dict(qty, entry, entry_date, high_close, cost_basis)
    pending_exits: dict = {}      # symbol -> reason (decided on previous close)
    pending_entries: list = []    # symbols ranked on previous close
    equity_points, res = {}, Result(equity=pd.Series(dtype=float))
    day_start_equity = p.start_capital

    for i, d in enumerate(dates):
        def px(s, col):
            df = data.get(s)
            return float(df.at[d, col]) if df is not None and d in df.index else None

        # 1) Execute orders decided on the previous close, at today's open.
        for s, reason in list(pending_exits.items()):
            o = px(s, "open")
            pos = positions.get(s)
            if o is None or pos is None:
                continue
            fill = _fill_price(o, "SELL", p)
            cash += pos["qty"] * fill - p.commission
            gross = pos["qty"] * (fill - pos["entry"])
            res.trades.append({"symbol": s, "entry_date": pos["entry_date"], "exit_date": d,
                               "qty": pos["qty"], "entry": pos["entry"], "exit": fill,
                               "pnl": gross - 2 * p.commission,
                               "ret": fill / pos["entry"] - 1 - 2 * p.commission / pos["cost_basis"],
                               "reason": reason})
            res.fills.append({"symbol": s, "side": "SELL", "qty": pos["qty"], "price": fill, "ts": d,
                              "reason": reason})
            del positions[s]
        pending_exits.clear()

        eq_open = cash + sum(pos["qty"] * (px(s, "open") or pos["entry"]) for s, pos in positions.items())
        day_halted = False
        if i > 0 and eq_open < day_start_equity * (1 - p.daily_loss_cap_pct):
            day_halted = True
            res.halted_days += 1
        if not day_halted:
            for s in pending_entries:
                if s in positions or len(positions) >= p.max_positions:
                    continue
                o, row = px(s, "open"), prev[s].loc[d] if d in prev[s].index else None
                if o is None or row is None or pd.isna(row["atr"]):
                    continue
                fill = _fill_price(o, "BUY", p)
                qty = strategy.position_size(eq_open, fill, float(row["atr"]), p)
                cost = qty * fill + p.commission
                if qty <= 0 or cost > cash:
                    continue
                cash -= cost
                positions[s] = {"qty": qty, "entry": fill, "entry_date": d, "high_close": fill,
                                "cost_basis": qty * fill}
                res.fills.append({"symbol": s, "side": "BUY", "qty": qty, "price": fill, "ts": d,
                                  "reason": "entry"})
        pending_entries = []

        # 2) After the close: update marks, decide tomorrow's orders using only today's data.
        for s, pos in positions.items():
            c = px(s, "close")
            if c is None:
                continue
            pos["high_close"] = max(pos["high_close"], c)
            reason = strategy.exit_signal(ind[s].loc[d], pos["high_close"], p)
            if reason:
                pending_exits[s] = reason
        if bool(mkt_ok.get(d, False)):
            cands = {}
            for s in data:
                if s in positions:
                    continue
                if d in ind[s].index and strategy.entry_signal(ind[s].loc[d]):
                    cands[s] = ind[s].loc[d]
            pending_entries = strategy.rank_candidates(cands)

        eq_close = cash + sum(pos["qty"] * (px(s, "close") or pos["entry"]) for s, pos in positions.items())
        equity_points[d] = eq_close
        day_start_equity = eq_close

    res.equity = pd.Series(equity_points, dtype=float)
    return res
