import json

import numpy as np
import pandas as pd
import pytest

from swing_bot import data, execute, robustness
from swing_bot.config import Params
from swing_bot.fills_ledger import FillsLedger

from test_swing import bars, choppy, uptrend

P = Params(trend_window=10, market_window=20, atr_window=5, slippage_bps=0, half_spread_bps=0)


# ---- data loader -------------------------------------------------------------------------------
def test_validate_rejects_nan_gaps_duplicates_and_bad_ohlc():
    good = bars(uptrend(60))
    data.validate_bars(good, "X")
    with pytest.raises(data.DataError):
        data.validate_bars(good.assign(close=np.where(np.arange(60) == 5, np.nan, good["close"])), "X")
    with pytest.raises(data.DataError):
        data.validate_bars(pd.concat([good.iloc[:10], good.iloc[40:]]), "X")  # ~20 business-day gap
    with pytest.raises(data.DataError):
        data.validate_bars(pd.concat([good, good.iloc[-1:]]), "X")
    broken = good.copy(); broken.iloc[3, broken.columns.get_loc("high")] = broken.iloc[3]["low"] * 0.5
    with pytest.raises(data.DataError):
        data.validate_bars(broken, "X")


def test_cache_roundtrip_records_provenance_and_detects_tampering(tmp_path):
    syms = ["SPY", "AAA"]
    fetched = []
    fake = lambda s, a, b: fetched.append(1) or {x: bars(uptrend(80, seed=i)) for i, x in enumerate(s)}
    f1, meta = data.load(syms, "2020-01-01", "2020-06-01", cache_dir=tmp_path, fetcher=fake)
    assert meta["source"] and meta["fetched_at"] and len(meta["sha256"]) == 64
    f2, _ = data.load(syms, "2020-01-01", "2020-06-01", cache_dir=tmp_path, fetcher=fake)
    assert len(fetched) == 1, "second call must use the cache"
    meta_path = tmp_path / "meta.json"; m = json.loads(meta_path.read_text()); m["sha256"] = "0" * 64
    meta_path.write_text(json.dumps(m))
    with pytest.raises(data.DataError):
        data.load(syms, "2020-01-01", "2020-06-01", cache_dir=tmp_path, fetcher=fake)


# ---- gate 5 ------------------------------------------------------------------------------------
def test_gate5_reports_every_variant_and_both_halves():
    frames = {"SPY": bars(choppy(seed=10, sigma=0.01, drift=0.001), start="2020-01-01"),
              "AAA": bars(choppy(seed=11), start="2020-01-01"), "BBB": bars(choppy(seed=12), start="2020-01-01")}
    g5 = robustness.gate5(frames, P, "2020-01-01", "2021-07-30",
                          halves=(("2020-01-01", "2020-10-30"), ("2020-11-02", "2021-07-30")))
    assert len(g5["detail"]) == 10 and set(g5) == {"pass", "detail"}
    assert g5["pass"] == all(d["pass"] for d in g5["detail"].values())


# ---- execution guards --------------------------------------------------------------------------
class FakeBroker:
    def __init__(self, equity=1000.0, status="accepted"):
        self.equity, self.status, self.orders, self.positions, self.filled = equity, status, [], {}, {}

    def get_account(self): return {"equity": self.equity}
    def list_positions(self): return dict(self.positions)

    def submit_order(self, symbol, qty, side, client_order_id):
        if any(o["cid"] == client_order_id for o in self.orders):
            raise AssertionError("duplicate client order id")
        oid = f"o{len(self.orders)}"
        self.orders.append({"id": oid, "cid": client_order_id, "symbol": symbol, "qty": qty, "side": side})
        return {"id": oid, "status": self.status}

    def get_order(self, oid):
        return self.filled.get(oid, {"status": "accepted", "filled_qty": 0, "filled_avg_price": None,
                                     "filled_at": None})


def setup(tmp_path, n=150):
    frames = {"SPY": bars(uptrend(n, seed=1), start="2020-01-01"), "AAA": bars(uptrend(n, seed=2), start="2020-01-01")}
    today = frames["SPY"].index[-1] + pd.offsets.BDay(1)
    ledger = FillsLedger(tmp_path / "l.sqlite3", bot="swing")
    return frames, today, ledger, str(tmp_path / "state.json")


def test_paper_endpoint_is_constant_and_enforced():
    assert execute.ALPACA_PAPER_URL == "https://paper-api.alpaca.markets"
    assert "live" not in execute.ALPACA_PAPER_URL


def test_normal_run_sends_entries_once_and_records_state(tmp_path):
    frames, today, ledger, st = setup(tmp_path)
    b = FakeBroker()
    out = execute.run_daily(b, frames, ledger, P, st, today=today, root=tmp_path)
    assert out["orders"] and all(o["side"] == "BUY" for o in b.orders)
    assert len(execute.load_state(st)["pending"]) == len(b.orders)


def test_kill_switch_file_and_env_block_all_orders(tmp_path, monkeypatch):
    frames, today, ledger, st = setup(tmp_path)
    (tmp_path / "KILL").write_text("")
    b = FakeBroker()
    with pytest.raises(execute.Halt, match="kill switch"):
        execute.run_daily(b, frames, ledger, P, st, today=today, root=tmp_path)
    assert b.orders == []
    (tmp_path / "KILL").unlink(); (tmp_path / "state.json").unlink()
    monkeypatch.setenv("SWING_KILL", "1")
    with pytest.raises(execute.Halt):
        execute.run_daily(b, frames, ledger, P, st, today=today, root=tmp_path)
    assert b.orders == []


def test_halt_persists_until_a_human_clears_it(tmp_path):
    frames, today, ledger, st = setup(tmp_path)
    (tmp_path / "KILL").write_text("")
    with pytest.raises(execute.Halt):
        execute.run_daily(FakeBroker(), frames, ledger, P, st, today=today, root=tmp_path)
    (tmp_path / "KILL").unlink()
    with pytest.raises(execute.Halt, match="previously halted"):
        execute.run_daily(FakeBroker(), frames, ledger, P, st, today=today, root=tmp_path)


def test_stale_data_halts(tmp_path):
    frames, today, ledger, st = setup(tmp_path)
    with pytest.raises(execute.Halt, match="stale"):
        execute.run_daily(FakeBroker(), frames, ledger, P, st, today=today + pd.offsets.BDay(5), root=tmp_path)


def test_reconciliation_mismatch_halts_without_orders(tmp_path):
    frames, today, ledger, st = setup(tmp_path)
    b = FakeBroker(); b.positions = {"AAA": 3.0}      # broker holds something our state does not know
    with pytest.raises(execute.Halt, match="reconciliation"):
        execute.run_daily(b, frames, ledger, P, st, today=today, root=tmp_path)
    assert b.orders == []


def test_rejected_order_halts(tmp_path):
    frames, today, ledger, st = setup(tmp_path)
    with pytest.raises(execute.Halt, match="not accepted"):
        execute.run_daily(FakeBroker(status="rejected"), frames, ledger, P, st, today=today, root=tmp_path)


def test_daily_loss_cap_blocks_entries_but_not_exits(tmp_path):
    frames, today, ledger, st = setup(tmp_path)
    execute.save_state(st, {"positions": {}, "pending": {}, "last_equity": 1000.0, "last_date": None, "halt": None})
    b = FakeBroker(equity=900.0)                       # down 10% vs yesterday, cap is 2%
    out = execute.run_daily(b, frames, ledger, P, st, today=today, root=tmp_path)
    assert out["entries_allowed"] is False and b.orders == []
    # exits still go out: hold AAA with a collapsed price
    crash = frames["AAA"].copy(); crash.iloc[-1] = crash.iloc[-1] * 0.5
    frames2 = {**frames, "AAA": crash}
    execute.save_state(st, {"positions": {"AAA": {"position_id": "AAA:x", "qty": 2.0, "entry": 100.0,
                            "high_close": 130.0}}, "pending": {}, "last_equity": 1000.0, "last_date": None,
                            "halt": None})
    b2 = FakeBroker(equity=900.0); b2.positions = {"AAA": 2.0}
    execute.run_daily(b2, frames2, ledger, P, st, today=today, root=tmp_path)
    assert [o["side"] for o in b2.orders] == ["SELL"]


def test_fills_sync_into_ledger_once_and_update_positions(tmp_path):
    frames, today, ledger, st = setup(tmp_path)
    b = FakeBroker()
    execute.run_daily(b, frames, ledger, P, st, today=today, root=tmp_path)
    first = b.orders[0]
    b.filled[first["id"]] = {"status": "filled", "filled_qty": first["qty"], "filled_avg_price": 111.0,
                             "filled_at": "2026-11-26T14:30:00Z"}
    b.positions = {first["symbol"]: first["qty"]}
    state = execute.load_state(st)
    execute.sync_fills(b, ledger, state); execute.sync_fills(b, ledger, state)   # idempotent
    rows = list(ledger.rows(execute.BOOK))
    assert len(rows) == 1 and state["positions"][first["symbol"]]["entry"] == 111.0
    execute.reconcile(b, state)
