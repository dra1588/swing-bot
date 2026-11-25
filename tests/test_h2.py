"""H2 tests, written BEFORE the engine (docs/PREREGISTRATION_H2.md section 7)."""
import json

import numpy as np
import pandas as pd
import pytest

from swing_bot import h2

SYMS = ["SPY", "EFA", "AGG", "VNQ", "DBC"]


def synth(seed=0, start="2005-01-03", end="2013-12-31", drift=0.0003, sigma=0.01):
    idx = pd.bdate_range(start, end)
    out = {}
    for i, s in enumerate(SYMS):
        rng = np.random.default_rng(seed * 10 + i)
        c = 100 * np.cumprod(1 + drift + rng.normal(0, sigma, len(idx)))
        o = np.concatenate([[c[0]], c[:-1]]) * (1 + rng.normal(0, 0.001, len(idx)))
        out[s] = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998,
                               "close": c}, index=idx)
    return out


def trend_frames(up=("SPY",), down=("EFA", "AGG", "VNQ", "DBC"), n_days=900):
    idx = pd.bdate_range("2005-01-03", periods=n_days)
    out = {}
    for s in SYMS:
        c = 100 * (1.0008 if s in up else 0.9992) ** np.arange(n_days)
        out[s] = pd.DataFrame({"open": c, "high": c * 1.001, "low": c * 0.999, "close": c}, index=idx)
    return out


W = ("2006-06-01", "2008-06-30")


def test_signal_invests_only_sleeves_above_their_10_month_average():
    frames = trend_frames()
    d = h2.month_end_dates(frames["SPY"].index)
    d = [x for x in d if x > pd.Timestamp("2006-06-01")][0]
    w = h2.sma_weights(frames, d, sma_months=10)
    assert w == {"SPY": 0.2}                      # only the rising sleeve; the rest stay in cash


def test_sleeve_with_too_little_history_is_cash():
    frames = trend_frames(up=SYMS, down=())
    early = h2.month_end_dates(frames["SPY"].index)[3]    # only ~4 month-ends exist
    assert h2.sma_weights(frames, early, sma_months=10) == {}


def test_signal_uses_only_data_up_to_the_decision_day():
    frames = synth()
    d = h2.month_end_dates(frames["SPY"].index)[40]
    base = h2.sma_weights(frames, d, 10)
    poisoned = {s: f.copy() for s, f in frames.items()}
    for f in poisoned.values():
        f.loc[f.index > d, ["open", "high", "low", "close"]] *= 50
    assert h2.sma_weights(poisoned, d, 10) == base


def test_engine_has_no_lookahead_future_prices_cannot_change_past_equity():
    frames = synth()
    cut = pd.Timestamp("2010-03-15")                      # mid-month: the last decision day is ~10 days earlier
    full = h2.run(frames, h2.sma_rule(10), ("2006-01-01", "2013-12-31"), cost_bps=10)
    poisoned = {s: f.copy() for s, f in frames.items()}
    for f in poisoned.values():
        f.loc[f.index > cut, ["open", "high", "low", "close"]] *= 50
    pois = h2.run(poisoned, h2.sma_rule(10), ("2006-01-01", "2013-12-31"), cost_bps=10)
    a, b = full.equity.loc[:cut], pois.equity.loc[:cut]
    assert len(a) == len(b) > 500 and np.allclose(a.values, b.values)
    trunc = h2.run({s: f.loc[:cut] for s, f in frames.items()}, h2.sma_rule(10), ("2006-01-01", cut), cost_bps=10)
    assert np.allclose(trunc.equity.loc[:cut].values, a.values)


def test_orders_fill_at_the_next_open_not_the_decision_close():
    idx = pd.bdate_range("2006-01-02", "2006-03-31")
    def mk(close, open_):
        return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + 1, "low": np.minimum(open_, close) - 1,
                             "close": close}, index=idx)
    base = np.full(len(idx), 100.0)
    opens, closes = base.copy(), base.copy()
    d = h2.month_end_dates(idx)[0]                         # 2006-01-31
    nxt = idx[idx.get_loc(d) + 1]
    opens[idx.get_loc(nxt):] = 110.0                       # gaps up at the fill day's open
    closes[idx.get_loc(nxt):] = 121.0
    frames = {s: mk(closes if s == "SPY" else base, opens if s == "SPY" else base) for s in SYMS}
    r = h2.run(frames, h2.const_rule({"SPY": 1.0}), ("2006-01-02", "2006-03-31"), cost_bps=10)
    shares = 1000.0 / 110.0                                # bought at the NEXT open (110), not the decision close (100)
    expected = -1.0 + shares * 121.0                       # cash after the 10 bps cost on 1000 notional
    assert r.equity.loc[nxt] == pytest.approx(expected)


def test_dev_evaluation_is_blind_to_every_date_after_2016():
    frames = synth(end="2019-12-31")
    clean = h2.evaluate(frames, h2.DEV, h2.DEV_HALVES, oos=False)
    poisoned = {s: f.copy() for s, f in frames.items()}
    for f in poisoned.values():
        f.loc[f.index > pd.Timestamp(h2.DEV[1]), ["open", "high", "low", "close"]] *= 37
    again = h2.evaluate(poisoned, h2.DEV, h2.DEV_HALVES, oos=False)
    assert json.dumps(clean, default=str, sort_keys=True) == json.dumps(again, default=str, sort_keys=True)


def test_dev_mode_refuses_holdout_halves():
    with pytest.raises(h2.WindowViolation):
        h2.evaluate(synth(end="2019-12-31"), h2.DEV, h2.HOLDOUT_HALVES, oos=False)
    with pytest.raises(h2.WindowViolation):
        h2.evaluate(synth(end="2019-12-31"), h2.HOLDOUT, h2.HOLDOUT_HALVES, oos=False)


def test_costs_reduce_final_equity():
    frames = synth(seed=3)
    lo = h2.run(frames, h2.sma_rule(10), W, cost_bps=0).equity.iloc[-1]
    hi = h2.run(frames, h2.sma_rule(10), W, cost_bps=50).equity.iloc[-1]
    assert hi < lo


def test_benchmark_6040_trades_into_its_weights_and_spy_holds_100():
    frames = synth(seed=4)
    r = h2.run(frames, h2.const_rule({"SPY": 0.6, "AGG": 0.4}), W, cost_bps=10)
    assert r.weights_log[0][1] == {"SPY": 0.6, "AGG": 0.4}
    r2 = h2.run(frames, h2.const_rule({"SPY": 1.0}), W, cost_bps=10)
    assert r2.weights_log[0][1] == {"SPY": 1.0}


def test_cash_earns_nothing_flat_when_nothing_is_invested():
    frames = trend_frames(up=(), down=SYMS)
    r = h2.run(frames, h2.sma_rule(10), ("2006-06-01", "2007-12-31"), cost_bps=10)
    assert np.allclose(r.equity.values, 1000.0)


def test_block_bootstrap_is_reproducible_and_sensible():
    rng = np.random.default_rng(0)
    b = rng.normal(0.004, 0.03, 120)
    assert h2.bootstrap_sharpe_win_rate(b, b) == 0.0                 # identical series never "wins"
    s = b + 0.01                                                      # uniformly better every month
    p1, p2 = h2.bootstrap_sharpe_win_rate(s, b), h2.bootstrap_sharpe_win_rate(s, b)
    assert p1 == p2 and p1 > 0.95


def test_year_concentration_and_drawdown_helpers():
    idx = pd.bdate_range("2010-01-01", "2012-12-31")
    eq = pd.Series(np.linspace(1000, 1300, len(idx)), index=idx)
    assert h2.year_concentration(eq) < 0.40
    assert h2.max_drawdown(pd.Series([100, 120, 90, 130])) == pytest.approx(-0.25)
    spike = pd.Series(1000.0, index=idx); spike.loc["2011-06-01":] = 1500.0
    assert h2.year_concentration(spike) > 0.9


def test_gate5_has_exactly_the_preregistered_variants():
    g5 = h2.gate5(synth(end="2016-12-31"), h2.DEV, h2.DEV_HALVES)
    assert set(g5["detail"]) == {"sma_months=8", "sma_months=12", "cost_bps=20",
                                 "half1 2007-01-01..2011-12-31", "half2 2012-01-01..2016-12-31"}


def test_holdout_is_single_use_and_needs_approval(tmp_path, monkeypatch):
    from swing_bot import h2_report
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        h2_report.main(["--holdout"])                                  # no approval flag
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "h2_holdout_result.json").write_text("{}")
    with pytest.raises(h2_report.HoldoutAlreadyRun):
        h2_report.main(["--holdout", "--i-approve-single-holdout-run"])
