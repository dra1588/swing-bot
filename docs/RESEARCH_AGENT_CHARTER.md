# Research agent charter (DRAFT v1, 25 Nov 2026)

Goal: an agent that scours public data sources, proposes ideas, and feeds results back so the system adapts.
The risk: an agent that searches many ideas and keeps the winners will find "winners" in pure noise. This charter makes
adaptation safe by keeping the agent on the proposing side and keeping every judgement behind the preregistration process.

## 1. What the agent may do
- Read public sources, summarise them and write **hypothesis cards** to `proposals/` (claim, source URL, exact data fields,
  proposed fixed rules, cost model, known lags, what the author already knows about past results).
- Run **collectors** that fetch and cache public data with provenance (source, timestamp, SHA-256), as the loader already does.
- Log every idea it tests, including failures, in the trial registry (section 3).
- Draft preregistrations for a human to approve.

## 2. What the agent may NOT do
- Place or approve orders, hold keys, or change any parameter of a registered hypothesis.
- Run a holdout or any single-use run, or edit a preregistration (it can only append dated versions for a human to merge).
- Tune a rule after seeing its result. A changed rule is a new hypothesis and a new registry entry.
- Use text or data that was not public at the decision time (every record needs a publish/acceptance timestamp).

## 3. Trial registry and the multiple-testing price
`registry/trials.csv` is append-only: id, date, hypothesis, variant, window, result, who ran it. Every development run of a
new idea counts, and so does every variant. With k = number of distinct hypotheses registered so far, gate 4 (bootstrap win
rate) must be at least **1 - 0.30 / k**. H1, H2 and H3 make k = 3, so the bar is 90%, not 70%. Each new idea raises it.
This is deliberately a price on searching.

## 4. How "adapt" works without overfitting
- Adaptation means a **new dated preregistration version** whose parameters were chosen only from data before a stated cut-off
  date and evaluated only on data after it (walk-forward). Re-fits at most once a quarter.
- Nothing changes inside a running paper or live strategy. A retrained version runs as a separate book, side by side.
- Forward (paper) results are the only fully clean evidence. A backtest pass only earns a forward test, never live money.

## 5. Allowed and disallowed sources
Allowed (free, public, documented lag): SEC EDGAR Forms 3/4/5 and 13F, the House Clerk periodic transaction reports, company
press releases and 8-Ks, Yahoo price bars. Respect each site's rules: the SEC allows at most 10 requests per second and wants a
declared User-Agent (use a project name, not personal details) ([SEC](https://www.sec.gov/os/accessing-edgar-data)).
Disallowed: anything behind a login or paywall, social-media or "top trader" leaderboards (selection bias: you only see the
survivors), paid signal groups, and Polymarket (blocked in Australia).

## 6. Cost and where it runs ($0 constraint)
- Collectors and tests run on GitHub Actions (free quota).
- An always-on LLM agent would need a paid API key, which breaks the $0 rule. Recommended: deterministic collectors on a
  schedule, and the LLM part (reading, proposing) run on demand in a Claude session, not unattended.
