import numpy as np
import pandas as pd

from swing_bot import backtest, metrics, strategy
from swing_bot.config import Params


def bars(closes, start="2020-01-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c}, index=idx)


P = Params(trend_window=10, market_window=20, atr_window=5, slippage_bps=0, half_spread_bps=0)


def uptrend(n=120, drift=0.004, seed=1):
    rng = np.random.default_rng(seed)
    return 100 * np.cumprod(1 + drift + rng.normal(0, 0.004, n))


def test_enters_in_uptrend_and_never_exceeds_caps():
    data = {"SPY": bars(uptrend()), "AAA": bars(uptrend(seed=2)), "BBB": bars(uptrend(seed=3))}
    res = backtest.run(data, P)
    assert res.fills, "an uptrend with a bullish market must trade"
    assert (res.equity > 0).all()


def test_no_trades_when_market_filter_is_bearish():
    falling = 100 * np.cumprod(1 - 0.004 * np.ones(120))
    data = {"SPY": bars(falling), "AAA": bars(uptrend())}
    res = backtest.run(data, P)
    assert res.fills == []


def choppy(n=400, seed=0, sigma=0.02, drift=0.0005):
    rng = np.random.default_rng(seed)
    return 100 * np.cumprod(1 + drift + rng.normal(0, sigma, n))


def test_no_lookahead_truncating_the_future_does_not_change_past_fills():
    data = {"SPY": bars(choppy(seed=10, sigma=0.01, drift=0.001)),
            "AAA": bars(choppy(seed=11)), "BBB": bars(choppy(seed=12)), "CCC": bars(choppy(seed=13))}
    full = backtest.run(data, P)
    assert len(full.trades) >= 5, "the test needs real entries AND exits to mean anything"
    key = lambda fills: [(f["symbol"], f["side"], f["ts"], round(f["price"], 8), round(f["qty"], 8))
                         for f in fills]
    for cut in (150, 220, 300, 380):
        short = {sym: df.iloc[:cut] for sym, df in data.items()}
        partial = backtest.run(short, P)
        cutoff = short["SPY"].index[-1]
        assert key(partial.fills) == key([f for f in full.fills if f["ts"] <= cutoff]), cut


def test_costs_reduce_results():
    data = {"SPY": bars(uptrend()), "AAA": bars(uptrend(seed=2))}
    free = backtest.run(data, P)
    costly = backtest.run(data, Params(**{**P.__dict__, "slippage_bps": 50, "half_spread_bps": 50}))
    assert costly.equity.iloc[-1] < free.equity.iloc[-1]


def test_trend_break_triggers_exit():
    up = list(uptrend(60, drift=0.006)); crash = [up[-1] * 0.8] * 30
    data = {"SPY": bars(up + [up[-1]] * 30), "AAA": bars(up + crash)}
    res = backtest.run(data, P)
    assert any(t["symbol"] == "AAA" and t["reason"] in ("trend_break", "trailing_stop") for t in res.trades)


def test_position_size_respects_risk_and_cap():
    q = strategy.position_size(1000, 50, 1.0, Params())
    assert q * 50 <= 0.20 * 1000 + 1e-9          # concentration cap
    assert q * 2.0 * 1.0 <= 0.01 * 1000 + 1e-9   # at most 1% equity at risk to the stop


def test_gate_checks_run_and_report_failure_honestly():
    data = {"SPY": bars(uptrend()), "AAA": bars(uptrend(seed=2))}
    res = backtest.run(data, P)
    g = metrics.gates(res, res.equity)
    assert g["g1_min_trades_150"]["pass"] is False   # tiny synthetic sample must not pass gate 1
    assert g["all_pass_without_g5"] is False


def test_bootstrap_ci_is_reproducible_and_brackets_the_mean():
    v = np.random.default_rng(0).normal(0.01, 0.05, 200)
    lo, hi = metrics.bootstrap_mean_ci(v)
    assert (lo, hi) == metrics.bootstrap_mean_ci(v)
    assert lo < v.mean() < hi
