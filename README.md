# swing-bot

Paper-only daily-bar swing strategy with preregistered pass/fail rules. See `docs/PREREGISTRATION.md`.

- `swing_bot/strategy.py` pure signal and sizing functions (no I/O, no look-ahead)
- `swing_bot/backtest.py` next-open fills, explicit costs, preregistered caps
- `swing_bot/metrics.py` Sharpe, drawdown, bootstrap interval, gate checks
- `swing_bot/fills_ledger.py` append-only ledger, copied unchanged from runner-bot (keep copies identical)

Status: engine and tests done. Not yet done: data loader, gate 5 robustness script, out-of-sample run,
paper execution loop. The out-of-sample window (2020-01-01 onward) must be run once, after the code is frozen.

```bash
pip install pandas numpy pytest
python -m pytest tests -q
```
