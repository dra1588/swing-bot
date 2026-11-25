# Phase 1: Swing strategy, preregistered pass/fail rules (DRAFT v1, 22 Nov 2026)

Status: draft for your approval. Nothing here is tuned on data. Once you approve, the file is committed and
may only change through a new dated version, never during a test run.

## 1. Scope and assumptions (all flagged, change any of them)
- Capital AUD 1,000 paper, risk 1% (about AUD 10) per trade. Assumed, not confirmed.
- Daily bars, liquid US large-cap stocks and ETFs. Free data (Alpaca IEX, Yahoo) is adequate for daily bars.
- No trade needs speed: orders are placed after the close or at the open, never inside the first minutes.
- AUD/USD conversion uses a dated rate stored with every fill. No invented rates.
- Live trading is out of scope for Phase 1. Whether an Australian resident can open a live Alpaca
  account is unconfirmed.
- With a small account, fixed brokerage on an ASX broker would swamp returns. Check the fee schedule
  of whichever broker you use before considering live.

## 2. Hypothesis (one, so there is nothing to cherry-pick)
Trend-following with a market filter: hold a stock only while it is above its 100-day average AND the
index (SPY) is above its 200-day average; exit on a close below the 100-day average or a 2x ATR(14) trailing
stop. Universe: fixed list of the 30 largest US stocks by market cap on 1 Jan 2020 plus SPY and QQQ.
Parameters: 100, 200, 14, 2. Four numbers, all fixed in advance. No optimisation is allowed.

If you prefer a different hypothesis, replace section 2 only. Sections 3 to 6 apply unchanged.

## 3. Cost model (applied to every test)
- Spread: half the quoted spread at the fill, or 5 bps if unknown.
- Slippage: 5 bps per side. Commission: broker's actual fee, or zero for Alpaca.
- Fills at the next open after the signal, never the close that produced it (no look-ahead).
- Splits and dividends adjusted. Survivorship bias disclosed: the universe is fixed as of 2020.

## 4. Backtest gates (all must hold, or the hypothesis is dropped)
Data: 1 Jan 2010 to 31 Dec 2019 for development, 1 Jan 2020 to 22 Nov 2026 as untouched out-of-sample.
The out-of-sample window is used once.
1. At least 150 closed trades out of sample.
2. Net of costs, beats buy-and-hold SPY on risk-adjusted return (Sharpe) out of sample.
3. Net expectancy per trade above zero, with the lower end of a 95% bootstrap interval above zero.
4. Maximum drawdown no worse than 25% (and no worse than SPY's own drawdown by more than 5 points).
5. Result holds in both halves of the out-of-sample period and for plus or minus 20% on each parameter.
   If it only works at one setting, it is overfit.
6. No single trade or single year provides more than 30% of total profit.
If any gate fails, stop and report. Do not "try one more variant".

## 5. Paper-trading gates (after the backtest passes)
- Minimum 12 weeks and 40 closed trades, fully automatic, parameters frozen.
- Live-vs-backtest slippage within 2x the modelled costs.
- Reconciliation clean every night (the trading-records check passes). A failed reconciliation halts trading.
- Paper drawdown stays below 15%. Breaching it ends the trial.
- Win rate and profit factor are reported with intervals, never as bare numbers.

## 6. Automation safety (fully automatic, paper)
- Daily loss cap 2% of equity; max 4 open positions; max 20% of equity in any one name.
- Kill switch: an environment flag or file that halts new orders within one cycle. Test it monthly.
- Halt on stale data (older than 1 trading day), on a failed reconciliation, or on any order that
  does not confirm.
- Orders only through the paper endpoint, hard-coded. A separate explicit change and your sign-off
  are needed before any live endpoint exists in the code.
- Full audit trail: every signal, order and fill goes to the append-only ledger, archived nightly to
  trading-records.

## 7. Live gate (not before)
All of section 4 and 5 passed, plus your explicit written approval, plus resolved legal and tax questions
(ASIC licensing position for automated personal trading, tax treatment of trading profits). Start with the
smallest size and a stricter loss cap.

## 8. What counts as failure (and it is a legitimate result)
No edge after costs is the most likely outcome of any simple strategy. Reporting that honestly is a
success of the process. The next step is then a different hypothesis, not tuning this one.

---
## v1.1 clarifications (22 Nov 2026, written while coding, before any real market data was run)
These make section 2 and 3 precise. They add no tuning freedom.
- Entry candidates are ranked by 100-day return (highest first), ties alphabetical. Slots are filled in that order.
- Position size (fractional shares): min(1% of equity / (2 x ATR14), 20% of equity / price), using equity and ATR as of the signal day's data.
- Signals use the close of day t; orders fill at the open of day t+1 with 5 bps slippage + 5 bps half-spread per side (10 bps per side total).
- The 2% daily loss cap halts NEW entries for the rest of that day. Exits are never blocked.
- Entry needs close > 100-day average, ATR14 > 0 and SPY close > its 200-day average. Exit on close < 100-day average or close < highest close since entry - 2 x ATR14.
- SPY and QQQ are tradable like any stock. Gates are evaluated on trades closed in the out-of-sample window only.
- Gate 5 (robustness: +-20% on each parameter, and both halves of the out-of-sample window) is a separate script that is still to be written; no result may be reported as passing until it exists.

---
## v1.2 definitions (25 Nov 2026, written before any real market data was fetched or run)
- Data: Yahoo Finance daily bars via yfinance with auto_adjust=True (split and dividend adjusted OHLC), cached with a
  SHA-256 and fetch timestamp. A gap longer than 5 business days, NaN, non-positive or inconsistent prices abort the run.
- Development window 2010-01-01 to 2019-12-31. Out-of-sample window 2020-01-01 to 2026-11-20 inclusive, run once.
  The single run is enforced in code: `results/oos_result.json` is written once and a second run is refused.
- Gate 5 "holds" means, for a variant or sub-period: mean net trade return > 0 AND strategy Sharpe > SPY buy-and-hold
  Sharpe over the same dates. All of these must hold: each of trend_window, market_window, atr_window, atr_mult at
  x0.8 and x1.2 (windows rounded to whole days, other parameters unchanged), and both halves of the out-of-sample
  window (2020-01-01 to 2023-06-30, and 2023-07-01 to 2026-11-20).
- Universe survivorship: the list is as of 1 Jan 2020 while the development window starts in 2010, so the
  development results are biased upward. Only the out-of-sample result counts.

---
## v1.3 disclosure and result (25 Nov 2026)
- **Protocol breach, disclosed.** The first `swing-dev` run (GitHub Actions run 45619506666, commit f4903e3) evaluated the
  out-of-sample HALVES inside gate 5, because the halves were hard-coded to 2020-2026 regardless of mode. Its log showed
  half 1 (2020-01-01..2023-06-30) = pass and half 2 (2023-07-01..2026-11-20) = fail. So the out-of-sample window is no
  longer untouched; any later out-of-sample result must be read with that in mind. Fixed in the commit that adds this
  note: development runs use development halves (2010-2014, 2015-2019) and the code refuses any date after 2019-12-31.
- **Development-window result (2010-2019, same run).** Gate 1 pass (442 trades). Gate 2 FAIL (Sharpe 0.705 vs SPY 0.922).
  Gate 3 pass (mean +1.19% per trade, 95% interval 0.41% to 2.10%). Gate 4 pass (max drawdown -19.2% vs SPY -19.3%).
  Gate 6 pass (largest trade 13.5%, largest year 26.6% of profit). Gate 5 FAIL: all 8 parameter variants failed.
  Note this window flatters the strategy (universe chosen as of 2020; survivorship).
- **Decision rule applied.** Section 4 says: if any gate fails, stop and report. Gates 2 and 5 failed on the development
  window, which is biased in the strategy's favour. No variant will be tried.
