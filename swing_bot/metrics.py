"""Performance metrics and the preregistered gate checks (docs/PREREGISTRATION.md section 4)."""
import numpy as np
import pandas as pd


def daily_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def sharpe(equity: pd.Series) -> float:
    r = daily_returns(equity)
    return float(np.sqrt(252) * r.mean() / r.std()) if len(r) > 2 and r.std() > 0 else float("nan")


def max_drawdown(equity: pd.Series) -> float:
    """Most negative peak-to-trough fraction, e.g. -0.18."""
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def bootstrap_mean_ci(values, n=5000, alpha=0.05, seed=12345):
    """95% percentile bootstrap interval of the mean. Fixed seed so a result is reproducible."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = rng.choice(v, size=(n, len(v)), replace=True).mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def concentration(trades: list) -> dict:
    """Largest single-trade and single-year share of total profit (gate 6)."""
    pnl = pd.Series([t["pnl"] for t in trades], dtype=float)
    total = pnl.sum()
    if total <= 0 or pnl.empty:
        return {"top_trade_share": float("nan"), "top_year_share": float("nan")}
    years = pd.Series(pnl.values, index=[pd.Timestamp(t["exit_date"]).year for t in trades])
    return {"top_trade_share": float(pnl.max() / total),
            "top_year_share": float(years.groupby(level=0).sum().max() / total)}


def gates(result, benchmark_equity: pd.Series) -> dict:
    """Gates 1-4 and 6. Gate 5 (parameter and sub-period robustness) needs repeated runs and
    lives in `robustness`. Each entry: {"value": ..., "pass": bool}."""
    rets = [t["ret"] for t in result.trades]
    lo, hi = bootstrap_mean_ci(rets)
    conc = concentration(result.trades)
    s_strat, s_bench = sharpe(result.equity), sharpe(benchmark_equity)
    dd, dd_bench = max_drawdown(result.equity), max_drawdown(benchmark_equity)
    out = {
        "g1_min_trades_150": {"value": len(rets), "pass": len(rets) >= 150},
        "g2_sharpe_beats_spy": {"value": (s_strat, s_bench),
                                "pass": bool(s_strat == s_strat and s_strat > s_bench)},
        "g3_expectancy_ci_above_zero": {"value": (float(np.mean(rets)) if rets else float("nan"), lo, hi),
                                        "pass": bool(lo == lo and lo > 0)},
        "g4_drawdown": {"value": (dd, dd_bench), "pass": bool(dd >= -0.25 and dd >= dd_bench - 0.05)},
        "g6_concentration_30pct": {"value": conc,
                                   "pass": bool(conc["top_trade_share"] == conc["top_trade_share"]
                                                and conc["top_trade_share"] <= 0.30
                                                and conc["top_year_share"] <= 0.30)},
    }
    out["all_pass_without_g5"] = all(v["pass"] for v in out.values())
    return out
