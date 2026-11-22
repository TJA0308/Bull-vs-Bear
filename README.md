# Bull vs. Bear

Two AI agents argue for and against a stock using its real SEC 10-K filing, and a third agent judges who won. Every claim is meant to quote the filing, and plain Python (not an LLM) checks that each quote really appears in it.

> **Not investment advice.** This is a research and argument tool built for learning.

## Status

Work in progress.

- [x] Ticker to CIK lookup (SEC EDGAR)
- [x] Find a company's latest 10-K and build its URL
- [x] Download and cache the filing, extract **Item 1A (Risk Factors)** and **Item 7 (MD&A)**
- [x] Shared Claude helper with token and cost logging (`llm.py`)
- [x] Bull and bear agents debating over several rounds (`debate.py`)
- [x] Judge agent with a scoring rubric
- [x] Citation checker: minimum length, exact fast path, fuzzy match (`rapidfuzz`, threshold 90), and every number must match; 27 tests across the project
- [x] Bias evaluation: swap bull/bear order and measure how often the verdict flips (`bias.py`, results below)
- [x] Interactive static site in `site/`, built from the saved results by `build_site.py`
- [ ] Publish on GitHub Pages (workflow added; needs a merge to `main` and Pages set to "GitHub Actions")

## How it works

```
ticker -> CIK -> latest 10-K -> Item 1A + Item 7 text
       -> bull agent <-> bear agent -> citation checker -> judge
       -> debates/TICKER.json -> static site
```

Debates are generated ahead of time and saved as JSON, so the site loads instantly and visitors never spend API credits.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project root (it is git-ignored, never commit it):

```
ANTHROPIC_API_KEY=your-key
SEC_USER_AGENT=Your Name your-email@example.com
```

The SEC requires the `User-Agent` to identify you and asks for no more than about 10 requests per second.

## Usage

```bash
python fetch.py NVDA
```

This downloads NVDA's latest 10-K (cached in `data/raw/`) and writes the extracted sections to `data/NVDA_risk_factors.txt` and `data/NVDA_mdna.txt`.

Tested on AAPL, NVDA, MSFT, TSLA, AMZN, GOOGL and META.

Run a full debate (2 rounds by default) and save it as JSON:

```bash
python debate.py AAPL
```

This writes `debates/AAPL.json` with the transcript, per-quote verification, the judge's scores and the cost. A 2-round debate is 5 Claude calls (Haiku 5.5) and costs about 1.5 cents.

Run the tests (none of them call the API):

```bash
python -m pytest
```

## Results

16 non-bank companies, one 2-round debate per setup (Claude Haiku 5.5). Raw numbers are in `results/` and `debates/`; re-print the bias report with `python bias.py --report` (add `--variant bear-first` for the second setup).

**Citations:** 190 of 192 quotes (99.0%) were found in the filing by code. The two misses scored 72 and 82 against a pass mark of 90. On Apple's filing, fabricated quotes scored 54 to 63, and quotes from the wrong company never passed.

The fuzzy score alone cannot see a changed figure: with one digit changed in the 98 quotes that contain a number, every one still scored 90 or more. So the checker also requires every number in the quote to appear in the part of the filing it matched, and rejects all 98. It still accepts a one-word wording change (91% of quotes with a word swapped), so a verified quote proves the words are in the filing, not that they support the claim.

**Judge bias test.** Each debate was judged 3 times with bull listed first and 3 times with bear listed first (96 judgments per setup), in two setups: the bull speaks first (original) or the bear speaks first.

| | Bull speaks first | Bear speaks first |
|---|---|---|
| Bull wins | 4% | 8% |
| Tie | 25% | 36% |
| Bear wins | 71% | 55% |
| Bonus for the side listed first (points of 30, 95% range) | +0.2 (-0.2 to +0.5) | +0.4 (-0.1 to +0.9) |
| Judge disagrees with itself, same order | 28% of debates | 19% |
| Majority verdict changes when order is swapped | 31% | 44% |
| Swap-and-average: disagreement afterward | 6% | 19% |

What this says, and does not say:

- **No clear effect of listing order on scores.** Both ranges include zero (the interval uses a t critical value, which is wider than 1.96 with only 16 debates).
- **The bear's edge is partly a debate-format flaw.** In the original format the bear always replies last. With the bear speaking first its share fell from 71% to 55%. But the bear still won about 7 times as often as the bull, so something else favors it. Candidates, none tested yet: the judge's taste for caution, the Risk Factors section making up most of the text, or the judge being the same model as the debaters.
- **Order swaps flip verdicts more than rerunning does only in the second setup** (44% against a 19% baseline), though the score bonus stays small. In the first setup the flip rate (31%) matches the baseline (28%).
- **Swap-and-average helped in one setup and not the other** (28% to 6%, then 19% to 19%), so it is not a reliable fix on this much data.
- **The listing-order test has a confound.** When the judge lists the side that spoke second first, it reads a reply before the argument it answers, so those results mix pure position bias with a scrambled conversation. Fixing that needs a different test design and a rerun of the judging (cheap, but not done yet).
- Only 16 debates per setup, so treat every number as a rough estimate.

## The site

`site/` is a static page (plain HTML, CSS and JavaScript) with a debate explorer, the bias lab and a quote-checker experiment. It reads `site/data.js`, which `build_site.py` generates from the saved debates and results.

```bash
python build_site.py            # regenerate site/data.js (needs the cached filings in data/raw)
python -m http.server 8123 --directory site   # preview at http://localhost:8123
```

`build_site.py` reads the cached filings in `data/raw/`, so run `python fetch.py TICKER` first for any company that is not cached. `.github/workflows/pages.yml` publishes `site/` to GitHub Pages on every push to `main`; it needs no secrets. One-time setup: repo Settings, Pages, Source: "GitHub Actions".

## Known limitations

- **Banks and some other filers** (for example JPM) incorporate MD&A by reference from a separate exhibit, so there is no MD&A in the 10-K body. `fetch.py` raises a clear error when a section is under 500 words instead of returning junk.
- **ETFs and foreign filers** have no 10-K, so the lookup raises an error.
- Section extraction uses regular expressions on the filing text, so unusual layouts may need pattern tweaks.

## Project layout

| File | Purpose |
|---|---|
| `fetch.py` | EDGAR lookup, filing download and cache, section extraction |
| `llm.py` | The one place that calls Claude: model, cost tracking, JSON parsing |
| `debate.py` | Bull and bear agents, judge, debate JSON |
| `citations.py` | Checks that each quoted passage really appears in the filing |
| `bias.py` | Order-swap test of the judge; writes `results/bias.json` |
| `results/` | Saved bias test results |
| `build_site.py` | Turns saved debates and results into `site/data.js` |
| `site/` | The static page (HTML, CSS, JavaScript, generated data) |
| `.github/workflows/pages.yml` | Publishes `site/` to GitHub Pages |
| `tests/` | pytest tests: citation checker, section extraction, bias statistics, debate-turn validation |
| `debates/` | Saved debates, one JSON file per ticker |
| `test_key.py` | Smoke test that the Claude API key works |
| `requirements.txt` | Pinned dependencies |
| `data/` | Cached filings and extracted text (git-ignored) |
