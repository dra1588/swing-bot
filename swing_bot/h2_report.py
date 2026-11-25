"""H2 gate report. `--dev` is repeatable (2007-2016 only). `--holdout` is single-use, enforced by a result file."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import data as data_mod, h2

RESULT = Path("results/h2_holdout_result.json")


class HoldoutAlreadyRun(RuntimeError):
    pass


def _git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def table(res) -> str:
    lines = [f"window {res['window']}  months {res['months']}",
             f"{'':16}{'Sharpe':>8}{'MaxDD':>9}{'Final':>10}"]
    for k in ("strategy", "benchmark_6040", "spy_buy_hold"):
        v = res[k]
        lines.append(f"{k:16}{v['sharpe']:8.3f}{v['max_dd']:9.1%}{v['final']:10.1f}")
    lines.append(f"{'gate':32} {'result':6} value")
    for k, v in res["gates"].items():
        lines.append(f"{k:32} {'PASS' if v['pass'] else 'FAIL':6} {v['value']}")
    lines.append(f"{'ALL GATES':32} {'PASS' if res['ALL_GATES_PASS'] else 'FAIL'}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dev", action="store_true")
    mode.add_argument("--holdout", action="store_true")
    ap.add_argument("--i-approve-single-holdout-run", action="store_true")
    ap.add_argument("--cache", default="data_h2")
    a = ap.parse_args(argv)
    if a.holdout:
        if not a.i_approve_single_holdout_run:
            sys.exit("refusing: the holdout is single-use; pass --i-approve-single-holdout-run after approval")
        if RESULT.exists():
            raise HoldoutAlreadyRun(f"{RESULT} exists: the holdout run has already been used")
    window, halves = (h2.HOLDOUT, h2.HOLDOUT_HALVES) if a.holdout else (h2.DEV, h2.DEV_HALVES)
    frames, meta = data_mod.load(h2.SYMBOLS, "2005-01-01", "2026-11-21", cache_dir=a.cache)
    res = h2.evaluate(frames, window, halves, oos=a.holdout)
    out = table(res)
    print(out)
    if a.holdout:
        RESULT.parent.mkdir(exist_ok=True)
        RESULT.write_text(json.dumps({"commit": _git_sha(), "data": meta, "result": res, "table": out},
                                     indent=2, default=str))
    return res


if __name__ == "__main__":
    main()
