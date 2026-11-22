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
