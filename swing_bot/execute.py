"""Daily paper execution. Run once after the US close. PAPER ONLY: the endpoint is a constant, not config.

Order of work each run: guards -> sync yesterday's fills into the ledger -> reconcile with the broker ->
plan from today's closed bars -> submit day orders (queued for the next open) -> confirm them.
Every halt leaves a reason in state.json and sends no orders.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import strategy

ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"   # hard-coded on purpose; never read from env
BOOK = "swing_paper"


class Halt(RuntimeError):
    """A safety guard tripped. No orders are sent."""


class AlpacaPaper:
    def __init__(self, key, secret, session=None):
        import requests
        assert ALPACA_PAPER_URL.startswith("https://paper-api."), "paper endpoint only"
        self.s = session or requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    def _req(self, method, path, **kw):
        r = self.s.request(method, ALPACA_PAPER_URL + path, timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def get_account(self):
        return {"equity": float(self._req("GET", "/v2/account")["equity"])}

    def list_positions(self):
        return {p["symbol"]: float(p["qty"]) for p in self._req("GET", "/v2/positions")}

    def submit_order(self, symbol, qty, side, client_order_id):
        o = self._req("POST", "/v2/orders", json={"symbol": symbol, "qty": str(qty), "side": side.lower(),
                      "type": "market", "time_in_force": "day", "client_order_id": client_order_id})
        return {"id": o["id"], "status": o["status"]}

    def get_order(self, order_id):
        o = self._req("GET", f"/v2/orders/{order_id}")
        return {"status": o["status"], "filled_qty": float(o.get("filled_qty") or 0),
                "filled_avg_price": float(o["filled_avg_price"]) if o.get("filled_avg_price") else None,
                "filled_at": o.get("filled_at")}


OK_STATUSES = {"new", "accepted", "pending_new", "accepted_for_bidding", "filled", "partially_filled"}
BAD_STATUSES = {"rejected", "canceled", "expired", "suspended"}


def killed(root=".") -> bool:
    return os.environ.get("SWING_KILL", "").lower() in ("1", "true", "yes") or (Path(root) / "KILL").exists()


def load_state(path):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {"positions": {}, "pending": {}, "last_equity": None,
                                                         "last_date": None, "halt": None}


def save_state(path, state):
    tmp = Path(str(path) + ".tmp"); tmp.write_text(json.dumps(state, indent=2, default=str))
    os.replace(tmp, path)


def check_stale(frames, p, today: pd.Timestamp):
    last = frames[p.market_symbol].index[-1]
    lag = int(np.busday_count(last.date(), today.date()))
    if lag > 1:
        raise Halt(f"stale data: last {p.market_symbol} bar {last.date()} is {lag} business days old")


def sync_fills(broker, ledger, state):
    """Record fills of orders submitted earlier. Idempotent: the order id is the ledger fill id."""
    for oid, info in list(state["pending"].items()):
        o = broker.get_order(oid)
        if o["status"] in BAD_STATUSES:
            raise Halt(f"order {oid} {info['symbol']} {info['side']} ended {o['status']}")
        if o["status"] == "filled":
            pid = info["position_id"]
            ledger.record(fill_id=oid, book=BOOK, position_id=pid, symbol=info["symbol"], side=info["side"],
                          qty=o["filled_qty"], price=o["filled_avg_price"], ts=o["filled_at"],
                          reason=info["reason"], paper=True)
            if info["side"] == "BUY":
                state["positions"][info["symbol"]] = {"position_id": pid, "qty": o["filled_qty"],
                                                      "entry": o["filled_avg_price"],
                                                      "high_close": o["filled_avg_price"]}
            else:
                state["positions"].pop(info["symbol"], None)
            del state["pending"][oid]


def reconcile(broker, state, tol=1e-6):
    held = broker.list_positions()
    mine = {s: pos["qty"] for s, pos in state["positions"].items()}
    # A pending (unfilled) order is not yet a position on either side.
    diffs = {s: (held.get(s, 0.0), mine.get(s, 0.0)) for s in set(held) | set(mine)
             if abs(held.get(s, 0.0) - mine.get(s, 0.0)) > tol}
    if diffs:
        raise Halt(f"reconciliation failed (broker, ledger): {diffs}")


def plan(frames, p, state, equity, entries_allowed):
    """Return a list of orders from today's closed bars. Pure given its inputs."""
    ind = {s: strategy.indicators(df, p) for s, df in frames.items()}
    orders = []
    for s, pos in state["positions"].items():
        row = ind[s].iloc[-1]
        pos["high_close"] = max(pos["high_close"], float(row["close"]))
        reason = strategy.exit_signal(row, pos["high_close"], p)
        if reason:
            orders.append({"symbol": s, "side": "SELL", "qty": pos["qty"], "reason": reason,
                           "position_id": pos["position_id"]})
    exiting = {o["symbol"] for o in orders}
    slots = p.max_positions - (len(state["positions"]) - len(exiting)) - sum(
        1 for i in state["pending"].values() if i["side"] == "BUY")
    if entries_allowed and slots > 0 and bool(strategy.market_ok(frames[p.market_symbol], p).iloc[-1]):
        cands = {s: ind[s].iloc[-1] for s in frames
                 if s not in state["positions"] and strategy.entry_signal(ind[s].iloc[-1])}
        today = frames[p.market_symbol].index[-1].date()
        for s in strategy.rank_candidates(cands)[:slots]:
            row = cands[s]
            qty = round(strategy.position_size(equity, float(row["close"]), float(row["atr"]), p), 4)
            if qty > 0:
                orders.append({"symbol": s, "side": "BUY", "qty": qty, "reason": "entry",
                               "position_id": f"{s}:{today}"})
    return orders


def run_daily(broker, frames, ledger, p, state_path="state.json", today=None, root="."):
    today = pd.Timestamp(today or datetime.now(timezone.utc).date())
    state = load_state(state_path)
    try:
        if state.get("halt"):
            raise Halt(f"previously halted and not cleared: {state['halt']}")
        if killed(root):
            raise Halt("kill switch is set")
        check_stale(frames, p, today)
        sync_fills(broker, ledger, state)
        reconcile(broker, state)
        equity = broker.get_account()["equity"]
        last = state.get("last_equity")
        entries_allowed = not (last and equity < last * (1 - p.daily_loss_cap_pct))
        orders = plan(frames, p, state, equity, entries_allowed)
        for o in orders:
            cid = f"swing-{today.date()}-{o['symbol']}-{o['side']}"   # same id on a retry: no duplicate order
            sub = broker.submit_order(o["symbol"], o["qty"], o["side"], cid)
            if sub["status"] not in OK_STATUSES:
                raise Halt(f"order for {o['symbol']} not accepted: {sub['status']}")
            state["pending"][sub["id"]] = {k: o[k] for k in ("symbol", "side", "reason", "position_id")}
        state.update(last_equity=equity, last_date=str(today.date()))
        return {"orders": orders, "entries_allowed": entries_allowed, "equity": equity}
    except Halt as exc:
        state["halt"] = str(exc)
        raise
    finally:
        save_state(state_path, state)
