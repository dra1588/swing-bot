> **H1 (daily single-stock trend following) was dropped on 2026-11-25:** it failed development gates 2 and 5
> (see `docs/PREREGISTRATION.md` v1.3). Its workflows (`swing-daily`, `swing-oos`) must not be enabled.
> **H2 (monthly tactical asset allocation)** is drafted in `docs/PREREGISTRATION_H2.md`, approved 2026-11-25, then **DROPPED the same day on the development window** (gates 3-6 failed; see `docs/PREREGISTRATION_H2.md` v1.1). Code: `swing_bot/h2.py`, `swing_bot/h2_report.py`; workflows `h2-dev` (repeatable) and `h2-holdout` (single use, typed confirmation). Holdout was NOT run and must not be.

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
