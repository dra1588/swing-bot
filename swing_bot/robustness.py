"""Gate 5: parameter and sub-period robustness, as defined in PREREGISTRATION v1.2."""
from dataclasses import replace

import numpy as np
import pandas as pd

from . import backtest, metrics

HALVES = (("2020-01-01", "2023-06-30"), ("2023-07-01", "2026-11-20"))


def _holds(data, params, start, end, spy_close):
    res = backtest.run(data, params, start=start, end=end)
    rets = [t["ret"] for t in res.trades]
    bench = spy_close.loc[pd.Timestamp(start):pd.Timestamp(end)]
    s_strat, s_bench = metrics.sharpe(res.equity), metrics.sharpe(bench)
    ok = bool(rets and np.mean(rets) > 0 and s_strat == s_strat and s_strat > s_bench)
    return {"pass": ok, "trades": len(rets), "mean_ret": float(np.mean(rets)) if rets else float("nan"),
            "sharpe": s_strat, "spy_sharpe": s_bench}


def variants(p):
    for name in ("trend_window", "market_window", "atr_window", "atr_mult"):
        for mult in (0.8, 1.2):
            v = getattr(p, name) * mult
            yield f"{name}x{mult}", replace(p, **{name: int(round(v)) if name != "atr_mult" else v})


def gate5(data, p, start, end, halves=HALVES):
    spy = data[p.market_symbol]["close"]
    detail = {name: _holds(data, vp, start, end, spy) for name, vp in variants(p)}
    for i, (a, b) in enumerate(halves):
        detail[f"half{i + 1} {a}..{b}"] = _holds(data, p, a, b, spy)
    return {"pass": all(d["pass"] for d in detail.values()), "detail": detail}
