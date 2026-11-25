"""H2: monthly tactical asset allocation. Rules and gates are fixed in docs/PREREGISTRATION_H2.md.

Signals use month-end closes up to the decision day; orders fill at the next trading day's open.
Cash earns 0%. Windows are enforced here, not left to callers.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SYMBOLS = ["SPY", "EFA", "AGG", "VNQ", "DBC"]
DEV = ("2007-01-01", "2016-12-31")
HOLDOUT = ("2017-01-01", "2026-11-20")
DEV_HALVES = (("2007-01-01", "2011-12-31"), ("2012-01-01", "2016-12-31"))
HOLDOUT_HALVES = (("2017-01-01", "2021-12-31"), ("2022-01-01", "2026-11-20"))
START_CAPITAL = 1000.0
COST_BPS = 10.0          # per side
SMA_MONTHS = 10


class WindowViolation(RuntimeError):
    pass


@dataclass
class Result:
    equity: pd.Series
    weights_log: list = field(default_factory=list)   # (decision_date, weights)


def month_end_dates(index) -> list:
    """Last trading day of each month, only where a later trading day exists (so a fill is possible)."""
    idx = pd.DatetimeIndex(index)
    return [d for d, nxt in zip(idx[:-1], idx[1:]) if nxt.to_period("M") != d.to_period("M")]


def sma_weights(frames, d, sma_months=SMA_MONTHS) -> dict:
    """20% per sleeve whose last month-end close is above the mean of its last `sma_months` month-end closes."""
    w = {}
    for s in SYMBOLS:
        c = frames[s]["close"].loc[:d]
        if c.empty:
            continue
        me = c.groupby(c.index.to_period("M")).last()
        if len(me) >= sma_months and me.iloc[-1] > me.iloc[-sma_months:].mean():
            w[s] = 1.0 / len(SYMBOLS)
    return w


def sma_rule(sma_months=SMA_MONTHS):
    return lambda frames, d: sma_weights(frames, d, sma_months)


def const_rule(weights: dict):
    return lambda frames, d: dict(weights) if all(not frames[s]["close"].loc[:d].empty for s in weights) else {}


def run(frames, rule, window, cost_bps=COST_BPS) -> Result:
    start, end = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    cal = frames["SPY"].index
    cal = cal[cal <= end]
    dates = [d for d in cal if d >= start]
    decision_days = {d for d in month_end_dates(cal) if d >= start}
    cash, shares, pending = START_CAPITAL, {}, None
    equity, log = {}, []
    for d in dates:
        if pending is not None:
            px = {s: float(frames[s]["open"].at[d]) for s in set(shares) | set(pending) if d in frames[s].index}
            eq_open = cash + sum(shares.get(s, 0.0) * p for s, p in px.items())
            for s in set(shares) | set(pending):
                if s not in px:
                    continue
                cur, tgt = shares.get(s, 0.0) * px[s], pending.get(s, 0.0) * eq_open
                cash -= (tgt - cur) + abs(tgt - cur) * cost_bps / 1e4
                shares[s] = tgt / px[s]
            pending = None
        equity[d] = cash + sum(sh * float(frames[s]["close"].at[d]) for s, sh in shares.items() if d in frames[s].index)
        if d in decision_days:
            pending = rule(frames, d)
            log.append((d, dict(pending)))
    return Result(pd.Series(equity, dtype=float), log)


# ---- metrics ----------------------------------------------------------------------------------
def monthly_returns(eq: pd.Series) -> np.ndarray:
    m = eq.groupby(eq.index.to_period("M")).last().values
    vals = np.concatenate([[eq.iloc[0]], m])
    return vals[1:] / vals[:-1] - 1.0


def sharpe_monthly(r) -> float:
    r = np.asarray(r, dtype=float)
    return float(np.sqrt(12) * r.mean() / r.std(ddof=1)) if len(r) > 2 and r.std(ddof=1) > 0 else float("nan")


def max_drawdown(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1.0).min()) if len(eq) else 0.0


def year_concentration(eq: pd.Series) -> float:
    """Largest single calendar year's share of total profit; inf if total profit is not positive."""
    total = float(eq.iloc[-1] - eq.iloc[0])
    if total <= 0:
        return float("inf")
    year_end = eq.groupby(eq.index.year).last()
    pnl = year_end.diff()
    pnl.iloc[0] = year_end.iloc[0] - eq.iloc[0]
    return float(max(pnl.max(), 0.0) / total)


def bootstrap_sharpe_win_rate(strat, bench, block=6, n=10000, seed=12345) -> float:
    s, b = np.asarray(strat, dtype=float), np.asarray(bench, dtype=float)
    m = len(s)
    rng = np.random.default_rng(seed)
    blocks = -(-m // block)
    starts = rng.integers(0, m, size=(n, blocks))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % m).reshape(n, -1)[:, :m]
    rs, rb = s[idx], b[idx]
    ss = rs.mean(axis=1) / rs.std(axis=1, ddof=1)
    sb = rb.mean(axis=1) / rb.std(axis=1, ddof=1)
    return float(np.mean(ss > sb))


def _pair(frames, window, sma_months=SMA_MONTHS, cost_bps=COST_BPS):
    strat = run(frames, sma_rule(sma_months), window, cost_bps)
    bench = run(frames, const_rule({"SPY": 0.6, "AGG": 0.4}), window, cost_bps)
    return strat, bench


def _claim_holds(strat_eq, bench_eq):
    ds, db = max_drawdown(strat_eq), max_drawdown(bench_eq)
    ss, sb = sharpe_monthly(monthly_returns(strat_eq)), sharpe_monthly(monthly_returns(bench_eq))
    g2 = bool(db < 0 and abs(ds) <= 0.75 * abs(db))
    g3 = bool(ss == ss and sb == sb and ss >= sb)
    return {"pass": g2 and g3, "dd_strategy": ds, "dd_6040": db, "sharpe_strategy": ss, "sharpe_6040": sb}


def gate5(frames, window, halves) -> dict:
    detail = {}
    for m in (8, 12):
        s, b = _pair(frames, window, sma_months=m)
        detail[f"sma_months={m}"] = _claim_holds(s.equity, b.equity)
    s, b = _pair(frames, window, cost_bps=2 * COST_BPS)
    detail[f"cost_bps={int(2 * COST_BPS)}"] = _claim_holds(s.equity, b.equity)
    for i, (a, z) in enumerate(halves):
        s, b = _pair(frames, (a, z))
        detail[f"half{i + 1} {a}..{z}"] = _claim_holds(s.equity, b.equity)
    return {"pass": all(v["pass"] for v in detail.values()), "detail": detail}


def _check_window(window, halves, oos):
    """A development run must never evaluate any date in the holdout window."""
    if oos:
        return
    dates = [window[1]] + [d for h in halves for d in h]
    if any(str(d) > DEV[1] for d in dates):
        raise WindowViolation(f"development run touches dates after {DEV[1]}: {sorted(dates)[-1]}")


def evaluate(frames, window, halves, oos=False) -> dict:
    _check_window(window, halves, oos)
    end = pd.Timestamp(window[1])
    frames = {s: f.loc[:end] for s, f in frames.items()}          # blind to everything after the window
    strat, bench = _pair(frames, window)
    spy = run(frames, const_rule({"SPY": 1.0}), window)
    rs, rb = monthly_returns(strat.equity), monthly_returns(bench.equity)
    claim = _claim_holds(strat.equity, bench.equity)
    win_rate = bootstrap_sharpe_win_rate(rs, rb)
    conc = year_concentration(strat.equity)
    g5 = gate5(frames, window, halves)
    g = {
        "g1_months_100": {"value": len(rs), "pass": len(rs) >= 100},
        "g2_drawdown_0.75x_6040": {"value": (claim["dd_strategy"], claim["dd_6040"]),
                                   "pass": bool(claim["dd_6040"] < 0 and abs(claim["dd_strategy"]) <= 0.75 * abs(claim["dd_6040"]))},
        "g3_sharpe_ge_6040": {"value": (claim["sharpe_strategy"], claim["sharpe_6040"]),
                              "pass": bool(claim["sharpe_strategy"] >= claim["sharpe_6040"])},
        "g4_bootstrap_70pct": {"value": win_rate, "pass": win_rate >= 0.70},
        "g5_robustness": {"value": {k: v["pass"] for k, v in g5["detail"].items()}, "pass": g5["pass"]},
        "g6_year_concentration_40pct": {"value": conc, "pass": bool(conc <= 0.40)},
    }
    return {"window": window, "months": len(rs),
            "strategy": {"sharpe": sharpe_monthly(rs), "max_dd": max_drawdown(strat.equity), "final": float(strat.equity.iloc[-1])},
            "benchmark_6040": {"sharpe": sharpe_monthly(rb), "max_dd": max_drawdown(bench.equity), "final": float(bench.equity.iloc[-1])},
            "spy_buy_hold": {"sharpe": sharpe_monthly(monthly_returns(spy.equity)), "max_dd": max_drawdown(spy.equity),
                             "final": float(spy.equity.iloc[-1])},
            "gates": g, "gate5_detail": g5["detail"], "ALL_GATES_PASS": all(v["pass"] for v in g.values())}
