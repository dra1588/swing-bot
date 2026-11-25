"""Entry point for the daily paper job: `python -m swing_bot.paper`. Secrets come from the environment only."""
import os
import sys
from datetime import datetime, timedelta, timezone

from . import data as data_mod, execute
from .config import Params, UNIVERSE
from .fills_ledger import FillsLedger


def main():
    p = Params()
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        sys.exit("ALPACA_API_KEY / ALPACA_SECRET_KEY are not set (paper keys only)")
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=520)            # enough warm-up for the 200-day market filter
    frames, meta = data_mod.load(UNIVERSE, str(start), str(end), cache_dir="data", refresh=True)
    ledger = FillsLedger("state/ledger.sqlite3", bot="swing")
    broker = execute.AlpacaPaper(key, secret)
    try:
        out = execute.run_daily(broker, frames, ledger, p, state_path="state/state.json")
    except execute.Halt as exc:
        print(f"HALT: {exc}")
        sys.exit(1)                               # the workflow fails, GitHub emails you, no orders were sent
    print(f"ok: equity {out['equity']:.2f}, entries_allowed={out['entries_allowed']}, orders={out['orders']}")


if __name__ == "__main__":
    main()
