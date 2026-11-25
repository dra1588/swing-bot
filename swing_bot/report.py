"""Gate report. `--dev` runs the development window freely. `--oos` is single-use (enforced by a result file)."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import data as data_mod, metrics, robustness, backtest
from .config import Params, UNIVERSE

DEV = ("2010-01-01", "2019-12-31")
OOS = ("2020-01-01", "2026-11-20")
RESULT = Path("results/oos_result.json")


class OosAlreadyRun(RuntimeError):
    pass


def _git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def evaluate(frames, p, window, with_gate5=True):
    res = backtest.run(frames, p, start=window[0], end=window[1])
    spy = frames[p.market_symbol]["close"].loc[window[0]:window[1]]
    g = metrics.gates(res, spy)
    if with_gate5:
        g5 = robustness.gate5(frames, p, *window)
        g["g5_robustness"] = {"value": {k: v["pass"] for k, v in g5["detail"].items()}, "pass": g5["pass"]}
    g["ALL_GATES_PASS"] = all(v["pass"] for k, v in g.items() if isinstance(v, dict) and "pass" in v)
    return g, res


def table(g) -> str:
    lines = [f"{'gate':32} {'result':8} value"]
    for k, v in g.items():
        if isinstance(v, dict) and "pass" in v:
            lines.append(f"{k:32} {'PASS' if v['pass'] else 'FAIL':8} {v['value']}")
    lines.append(f"{'ALL GATES':32} {'PASS' if g['ALL_GATES_PASS'] else 'FAIL'}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dev", action="store_true")
    mode.add_argument("--oos", action="store_true")
    ap.add_argument("--i-approve-single-oos-run", action="store_true")
    ap.add_argument("--cache", default="data")
    a = ap.parse_args(argv)
    p = Params()
    if a.oos:
        if not a.i_approve_single_oos_run:
            sys.exit("refusing: the OOS window is single-use; pass --i-approve-single-oos-run after approval")
        if RESULT.exists():
            raise OosAlreadyRun(f"{RESULT} exists: the out-of-sample run has already been used")
    window = OOS if a.oos else DEV
    frames, meta = data_mod.load(UNIVERSE, "2009-01-01", "2026-11-21", cache_dir=a.cache)
    g, res = evaluate(frames, p, window)
    out = table(g)
    print(out)
    if a.oos:
        RESULT.parent.mkdir(exist_ok=True)
        RESULT.write_text(json.dumps({"commit": _git_sha(), "data": meta, "window": window, "gates": g,
                                      "table": out}, indent=2, default=str))
    return g


if __name__ == "__main__":
    main()
