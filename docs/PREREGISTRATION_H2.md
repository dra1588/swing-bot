# Hypothesis 2: monthly tactical asset allocation (DRAFT v1, 25 Nov 2026)

Status: draft for approval. No H2 code has been written and no H2 data has been fetched. Once approved this file is
committed unchanged; later edits are appended as new dated versions only.

## 0. Why this, and what we learned from H1
H1 (daily trend-following on 30 single stocks) failed its development gates: it earned less per unit of risk than
holding SPY (Sharpe 0.705 vs 0.922) and broke under +-20% parameter changes. We also learned:
- Single-stock universes chosen with hindsight carry survivorship bias. H2 uses broad ETFs, which do not have that bias.
- Hard-coded dates leaked the out-of-sample window. H2 enforces windows in code, with tests written first.
- H1's claim was "beats buy-and-hold on return per risk". That is the hardest claim to make. H2 makes a narrower,
  literature-based claim that can be tested honestly.

## 1. Claim (one sentence, fixed in advance)
Holding each of five broad asset classes only while it trades above its 10-month average, and cash otherwise,
**cuts the worst drawdown versus a 60/40 portfolio by at least a quarter, without a worse Sharpe ratio, after costs.**
It does not claim higher returns than SPY. Failure of either half of the claim means H2 is dropped.

Source of the idea: the public "tactical asset allocation" literature (a 10-month moving-average rule on broad asset
classes). **Hindsight warning:** the author of this document knows that idea performed reasonably well in published
history. That counts as partial prior knowledge of the results, so only the forward paper-trading period (section 6)
is fully clean evidence.

## 2. Rules (all parameters fixed here; no tuning)
- Universe, equal 20% sleeves: SPY (US stocks), EFA (international stocks), AGG (US bonds), VNQ (real estate),
  DBC (commodities).
- Signal on the last trading day of each month, using month-end adjusted closes: a sleeve is invested if its close is
  above the simple average of its last 10 month-end closes, otherwise that sleeve is held in cash.
- Orders fill at the next trading day's open. Cost 10 bps per side (5 slippage + 5 half-spread). Commission 0.
- Cash earns 0% (conservative; no T-bill return assumed). Rebalance only at month-end signals; no intra-month action.
- Data: Yahoo daily bars via yfinance auto_adjust=True, same loader and checks as H1. A sleeve with no data yet (DBC
  starts in 2006) is held in cash until its 10th month-end close exists.
- Benchmarks: (a) 60/40 = 60% SPY / 40% AGG, rebalanced monthly, same costs; (b) SPY buy-and-hold, reported for context.

## 3. Windows (enforced in code, tested before any run)
- Development: 2007-01-01 to 2016-12-31 (includes 2008). Runs repeatably. The code refuses any date after 2016-12-31.
- Holdout: 2017-01-01 to 2026-11-20, run exactly once, via a single-use result file as in H1.
- Disclosure: the holdout period overlaps dates whose outcome was seen for H1's gate-5 halves (a different strategy
  and universe). This is mild contamination and is noted, not hidden.

## 4. Gates (all must hold on the holdout; the same gates are computed, for information only, on development)
1. **Enough data:** at least 100 monthly observations in the window.
2. **Drawdown claim:** strategy max drawdown is no worse than 0.75 x the 60/40 benchmark's max drawdown.
3. **Sharpe claim:** strategy Sharpe >= 60/40 Sharpe (annualised from monthly returns).
4. **Statistical support:** block bootstrap (block length 6 months, 10,000 resamples, fixed seed) of the monthly return
   series: the strategy's Sharpe exceeds 60/40's in at least 70% of resamples.
5. **Robustness:** gates 2 and 3 also hold with the average window at 8 months and at 12 months, with costs doubled
   to 20 bps per side, and in both halves of the holdout (2017-01..2021-12 and 2022-01..2026-11).
6. **Not one lucky stretch:** no single calendar year contributes more than 40% of the strategy's cumulative profit.
If any gate fails: stop, report, no variant. A pass does not authorise live money; it authorises section 6 only.

## 5. Practical notes (assumptions, not rules)
- Monthly trading means about 5 sleeves x 12 months of orders at most, so costs and AUD 1,000 capital are workable
  using fractional ETF shares. Currency effects (AUD/USD) are ignored in the backtest and recorded at paper fill time.
- Expected outcome, stated before looking: drawdown reduction is plausible; beating 60/40 on Sharpe is uncertain
  because the 2017-2026 period was strong for stocks and hard on bonds in 2022. A failure here is a normal result.

## 6. After a pass: forward paper test
At least 6 months of automatic paper trading with the H1 execution guards (kill switch, stale-data halt,
reconciliation, daily loss cap, order confirmation), frozen parameters, ledger archived. Only then discuss live money,
and only with your written approval and the legal and tax questions answered.

## 7. Build order (so a leak cannot recur)
1. Tests for window enforcement and no-look-ahead month-end signals, written first.
2. Engine and gates. 3. Development run (free to repeat). 4. Your go. 5. One holdout run.

---
## v1.1 result (25 Nov 2026): H2 DROPPED on the development window
Source: GitHub Actions run 45622075478 (`h2-dev`, commit c903d7c), window 2007-01-01..2016-12-31, 120 months, all 36 tests passing
in the same job. The holdout was NOT run and will not be run.

| | Sharpe | Max drawdown | Final (from 1000) |
|---|---|---|---|
| H2 strategy | 0.427 | -15.7% | 1,326.8 |
| 60/40 benchmark | 0.668 | -35.7% | 1,785.3 |
| SPY buy-and-hold | 0.501 | -55.2% | 1,907.4 |

Gates: 1 PASS (120 months). 2 PASS (drawdown 44% of the 60/40's). 3 FAIL (Sharpe 0.427 vs 0.668). 4 FAIL (bootstrap win rate 18%).
5 FAIL (8-month, 12-month and doubled-cost variants failed; half 1 2007-2011 passed, half 2 2012-2016 failed).
6 FAIL (one year provided 46.5% of profit).

Reading: the drawdown half of the claim held clearly; the Sharpe half did not. Section 1 says failing either half drops H2.
Per section 4, no variant will be tried (no cash interest, no other average lengths, no other ETFs). Any follow-up idea is a NEW
hypothesis with its own preregistration, chosen knowing this result.
