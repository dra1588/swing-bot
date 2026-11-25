# swing-bot

Paper-only daily-bar swing strategy with preregistered pass/fail rules. See `docs/PREREGISTRATION.md`.

- `swing_bot/strategy.py` pure signal and sizing functions (no I/O, no look-ahead)
- `swing_bot/backtest.py` next-open fills, explicit costs, preregistered caps
- `swing_bot/metrics.py` Sharpe, drawdown, bootstrap interval, gate checks
- `swing_bot/fills_ledger.py` append-only ledger, copied unchanged from runner-bot (keep copies identical)

Status (25 Nov 2026): engine, data loader, gate checks (1-6), single-use OOS runner, paper execution loop
with guards, and workflows are written and unit-tested offline (20 tests). **No real market data has been run yet**
(the build container cannot reach data hosts); that happens in GitHub Actions.

Workflows: `tests` (every push), `swing-dev` (2010-2019 report, repeatable), `swing-daily` (paper job, weekdays),
`swing-oos` (single use, needs the typed confirmation).

Secrets to set (Settings > Secrets and variables > Actions): `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` (PAPER keys only).
Optional variable `SWING_KILL=1` halts all orders; a file named `KILL` in the repo root does the same.
Do not enable `swing-daily` until `swing-dev` has been reviewed and the OOS result is in.

```bash
pip install -r requirements.txt
python -m pytest tests -q
python -m swing_bot.report --dev
```
