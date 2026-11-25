"""Phase C: is the bear's edge caused by the debate's INPUT?

Phase B showed the judge model matters (bear share 65% -> 29%). Here the judge
is fixed (Haiku 5.5, speaking order, like the original) and we change what the
debaters see. Two conditions, 16 companies each, bull speaks first, 2 rounds:

  rerun     same input as the original ("full": all of Items 1A and 7).
            A NOISE CONTROL: debaters are random, so a second run of the very
            same setup shows how far the bear's share moves by chance alone.
  balanced  the first 2,500 words of Item 1A plus the first 2,500 words of
            Item 7, so neither section outweighs the other. If Risk Factors
            being most of the text is what favors the bear, this should help
            the bull.

DECISION RULE, fixed BEFORE any paid run (committed first, so git history shows it):

  original = bear's share of Haiku judgments on the saved base debates
             (results/chronological.json, "base" setup).
  N        = |bear share(rerun) - original|             the noise gap
  baseline = (original + bear share(rerun)) / 2
  E        = bear share(balanced) - baseline            the input effect

  N >= 20 points                        -> "too noisy to read": rerunning the
                                           same input moves the share as much as
                                           the effect we look for.
  |E| >= max(20, 2 * N)                 -> "input-driven"
  |E| < 10                              -> "not input-driven"
  anything else                         -> "inconclusive"

The 20 and 10 are the same DRIFT_BIG / DRIFT_SMALL used for Phase B. With 16
debates (48 judgments, which are not independent) a share is only good to
about +/-14 points, so smaller differences should not be read as findings.

RESULT (run 2026-11-24; 16 companies per condition; $0.47 over 256 calls):

  bear's share of judgments: original 71%, rerun 42%, balanced 58%.
  Noise gap 29 points, so the rule's verdict is "too noisy to read": the
  question of whether balancing the input helps the bull is NOT answered.

  What the rerun did show (a finding, not a failure): regenerating debates from
  identical input moved the bear's share by 29 points, mostly by turning bear
  wins into ties (bull 6% -> 0%, tie 23% -> 58%). Per-company shares did not
  repeat (rank correlation +0.03; AAPL went 67% -> 0%). So one debate per
  company is too little data to read a share like "71%" to better than tens of
  points. Judging the same debates twice (as Phase B did) removes that noise,
  which is why Phase B's paired comparison still stands.

  Post-hoc, not part of the pre-set rule: the mean score margin (bull minus
  bear, 30-point scale) moved much less than the win share: -1.96 original,
  -1.40 rerun, -1.88 balanced, and the bull won only 0 to 10% of judgments in
  every condition. The sign of the bear's edge looks stable; its size does not.

Usage:
    python phase_c.py                 # run both conditions (about 50 cents), then report
    python phase_c.py rerun           # run one condition
    python phase_c.py --report        # analyze saved results, no API calls
"""
import json
import os
import sys

from bias import (CHRONO_PATH, DRIFT_BIG, DRIFT_SMALL, TICKERS, bear_share,
                  criterion_gaps, judge_in_speaking_order, load_results, save_results)
from debate import run_debate, save_debate
from llm import totals

CONDITIONS = {
    "rerun": {"input_mode": "full"},
    "balanced": {"input_mode": "balanced"},
}
RESULTS_PATH = os.path.join("results", "phase_c.json")


def condition_dir(name):
    return os.path.join("debates", "variants", f"phase-c-{name}")


def run_condition(name, tickers=None, results_path=RESULTS_PATH, out_dir=None, input_mode=None):
    """Generate one debate per ticker, judge it in speaking order, save as we go.

    input_mode defaults to the one registered for `name` in CONDITIONS; Phase D
    passes it explicitly for its numbered repeat draws."""
    out_dir = out_dir or condition_dir(name)
    input_mode = input_mode or CONDITIONS[name]["input_mode"]
    results = load_results(results_path)
    done = results.setdefault(name, {})
    for ticker in tickers or TICKERS:
        if ticker in done:
            print(f"{name}/{ticker}: already done, skipping")
            continue
        print(f"\n=== {ticker} ({name}) ===")
        try:
            debate_file = os.path.join(out_dir, f"{ticker}.json")
            if os.path.exists(debate_file):  # generated earlier, judging was what failed
                with open(debate_file, encoding="utf-8") as f:
                    debate = json.load(f)
            else:
                debate = run_debate(ticker, bull_first=True, input_mode=input_mode)
                save_debate(debate, out_dir)
            done[ticker] = judge_in_speaking_order(debate)
        except Exception as e:  # one bad filing should not stop the batch
            print(f"{name}/{ticker}: FAILED ({type(e).__name__}: {e})")
        save_results(results, results_path)
    return results


def rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a, b):
    """Rank correlation between two lists, or None if one has no spread."""
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return None if den == 0 else num / den


def phase_c_verdict(noise_gap, effect):
    """Apply the pre-set rule (see the module docstring)."""
    if noise_gap >= DRIFT_BIG:
        return "too noisy to read"
    if abs(effect) >= max(DRIFT_BIG, 2 * noise_gap):
        return "input-driven"
    if abs(effect) < DRIFT_SMALL:
        return "not input-driven"
    return "inconclusive"


def compare_conditions(original, rerun, balanced):
    """Each argument is {ticker: [run, ...]}. Only tickers present in all three count."""
    common = sorted(set(original) & set(rerun) & set(balanced))
    if not common:
        return None
    pick = lambda runs: {t: runs[t] for t in common}
    o, r, b = (bear_share(pick(x)) for x in (original, rerun, balanced))
    noise_gap = abs(o - r)
    baseline = (o + r) / 2
    effect = b - baseline
    per_ticker = lambda runs: [bear_share({t: runs[t]}) for t in common]
    return {
        "debates": len(common),
        "bear_share": {"original": round(o, 1), "rerun": round(r, 1), "balanced": round(b, 1)},
        "noise_gap": round(noise_gap, 1),
        "effect": round(effect, 1),
        "verdict": phase_c_verdict(noise_gap, effect),
        "criterion_gaps": {"original": criterion_gaps(pick(original)),
                           "rerun": criterion_gaps(pick(rerun)),
                           "balanced": criterion_gaps(pick(balanced))},
        # Do the same companies lean bear in both runs? (descriptive, no rule)
        "same_company_agreement": spearman(per_ticker(original), per_ticker(rerun)),
    }


def print_report(c):
    if c is None:
        print("No tickers finished in all three conditions yet.")
        return
    s, g = c["bear_share"], c["criterion_gaps"]
    print(f"\n=== Phase C: inputs vs the bear's edge ({c['debates']} debates per condition) ===")
    print(f"bear's share of Haiku judgments:  original {s['original']:.0f}%   "
          f"rerun {s['rerun']:.0f}%   balanced {s['balanced']:.0f}%")
    print(f"noise gap (original vs rerun): {c['noise_gap']:.0f} points")
    print(f"input effect (balanced minus the average of the two full runs): {c['effect']:+.0f} points")
    agree = c["same_company_agreement"]
    print("same-company agreement, original vs rerun (rank correlation): "
          + ("n/a" if agree is None else f"{agree:+.2f}"))
    for name in ("original", "rerun", "balanced"):
        print(f"bull-minus-bear by criterion, {name:9}: {g[name]}")
    print(f"rule (noise < {DRIFT_BIG}; effect >= max({DRIFT_BIG}, 2 x noise) or < {DRIFT_SMALL}): {c['verdict']}")


def load_original():
    return load_results(CHRONO_PATH).get("base", {})


def report():
    saved = load_results(RESULTS_PATH)
    print_report(compare_conditions(load_original(), saved.get("rerun", {}), saved.get("balanced", {})))


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--report" in args:
        report()
        sys.exit()
    names = [a for a in args if not a.startswith("-")] or list(CONDITIONS)
    unknown = [n for n in names if n not in CONDITIONS]
    if unknown:
        sys.exit(f"Unknown condition {unknown[0]!r}. Choose from: {', '.join(CONDITIONS)}")
    for name in names:
        run_condition(name)
    print(f"\ncost this run: ${totals['cost']:.4f} over {totals['calls']} calls")
    report()
