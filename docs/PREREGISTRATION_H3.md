# Hypothesis 3: copy well-informed buyers (insider cluster purchases) (DRAFT v1, 25 Nov 2026)

Status: draft for approval. No H3 code written, no H3 data fetched. Charter: `docs/RESEARCH_AGENT_CHARTER.md`.

## 0. What "copy brokers doing well" can honestly mean
I cannot see anyone's broker account. What is public and free is what well-informed people file:
- **Corporate insiders (SEC Form 4):** open-market purchases, filed within two business days. Short lag, free.
- Fund managers (13F): filed up to 45 days after quarter-end, so mostly stale. Congress members: up to 45 days late and
  a small, noisy sample. Both are weaker than insiders. Social "top trader" lists are rejected (selection bias).
H3 therefore copies insiders, and only when several buy together.

## 1. Claim (fixed in advance)
After a cluster of insider open-market purchases, holding the stock for 60 trading days **earns more than the small-cap index
(IWM) over the same days, net of costs and a stated survivorship haircut, with a Sharpe ratio no worse than IWM's.**

## 2. Rules (no tuning)
- Source: SEC Insider Transactions Data Sets (Forms 3/4/5, free quarterly files). Field names must be read from the actual files
  first; an inspect-schema step precedes any rule code.
- Event: transaction code P (open-market purchase) by at least **3 distinct insiders** within a trailing 30 calendar days,
  cluster total value at least **$100,000**. Signal date = the filing date on which the third insider's purchase becomes
  public. Filings after the US close count for the next trading day.
- Universe filter (from Yahoo bars): price at least $5, 20-day average dollar volume at least $2 million.
- Entry at the next trading day's open. Hold **60 trading days**, exit at the open of day 61. No stop. One position per stock.
- Max 10 concurrent positions, 10% of equity each. If more signals than slots, higher cluster dollar value first.
- Cost **30 bps per side** (small caps), commission 0. Cash earns 0%.
- Benchmarks: IWM (primary), SPY (context).

## 3. Data problem, stated plainly
Free price data (Yahoo) has few delisted stocks. Insider buying clusters happen often before bankruptcies, so a backtest on today's
surviving tickers overstates results. Therefore: (a) backtest results are an **upper bound**; (b) gate 3 subtracts a **2.0
percentage-point per-trade survivorship haircut**, chosen in advance and arbitrary; (c) only forward paper trading is clean.

## 4. Windows (enforced in code, tests first, as in H2)
Development 2007-01-01..2016-12-31 (repeatable; code refuses later dates). Holdout 2017-01-01..2026-11-20, single use,
result file enforced. The 2017-2026 dates overlap results seen for earlier hypotheses; disclosed, mild.

## 5. Gates (all required on the holdout; no variants if one fails)
1. At least 150 completed trades.
2. Strategy Sharpe >= IWM Sharpe (monthly returns).
3. Mean 60-day excess return over IWM (same dates), **minus the 2.0 pp haircut**, is above zero with a 95% bootstrap lower bound above zero.
4. Block bootstrap of monthly returns: strategy Sharpe beats IWM in at least **90%** of resamples (charter: 1 - 0.30/3).
5. Robustness: cluster size 2 and 4, hold 40 and 80 days, and cost 60 bps each still satisfy gates 2 and 3.
6. No single trade above 10% of total profit and no single year above 40%.

## 6. After a pass
At least 6 months of forward paper trading, then a separate decision about live money with your written approval and the legal and
tax questions answered. Expected outcome stated now: small-cap insider buying has published evidence of an edge that has shrunk and
sits where trading costs are highest, so a clean failure is plausible.

## 7. Build order
1. Inspect-schema workflow on the real SEC files. 2. Window-enforcement and no-look-ahead tests. 3. Engine and gates.
4. Development run, your review. 5. One holdout run. 6. Forward paper book.
