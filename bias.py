"""Does the judge's verdict depend on which side is listed first?

For each ticker: run ONE debate, then have the judge score that same debate
JUDGE_RUNS times with bull listed first and JUDGE_RUNS times with bear listed
first. The arguments are identical, so any systematic difference between the
two orders is position bias, not a difference in the debate.

Repeated runs in the SAME order measure plain randomness, which is the
baseline a "flip" has to beat before we call it bias.

Usage:
    python bias.py                  # run the default tickers (skips finished ones)
    python bias.py NVDA MSFT        # run just these
    python bias.py --report         # re-analyze saved results, no API calls
    python bias.py --chrono         # re-judge the saved debates in speaking order
    python bias.py --chrono --report
    python bias.py --chrono --judge-model claude-sonnet-5-5   # same debates, different judge
    python bias.py --compare claude-sonnet-5-5                # judge comparison, no API calls

The listing-order test above scrambles the conversation whenever the side
listed first is not the side that spoke first. --chrono is the clean
counterpart: the judge always reads the debate in the order it happened, so
any preference for a side cannot come from a reply appearing before the
argument it answers.
"""
import glob
import json
import os
import sys
from collections import Counter

from debate import judge, run_debate, save_debate
from llm import MODEL

TICKERS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
    "AMD", "ADBE", "CRM", "COST", "WMT", "KO", "PEP", "NKE",
]
JUDGE_RUNS = 3

# Experiment variants. "base" is the original setup (bull always speaks first,
# so bear always gets the last word). "bear-first" flips who speaks first.
VARIANTS = {
    "base": {"bull_first": True},
    "bear-first": {"bull_first": False},
}


def results_path(variant):
    name = "bias.json" if variant == "base" else f"bias_{variant}.json"
    return os.path.join("results", name)


def debate_dir(variant):
    # Variant debates go in a subfolder so they never overwrite the base ones.
    return "debates" if variant == "base" else os.path.join("debates", "variants", variant)


def margin(verdict):
    """Bull's total score minus bear's. Positive means the judge liked bull."""
    scores = verdict["scores"]
    return sum(scores["bull"].values()) - sum(scores["bear"].values())


def judge_both_orders(rounds):
    """Judge the same debate JUDGE_RUNS times in each presentation order."""
    out = {"bull_first": [], "bear_first": []}
    for first in ("bull", "bear"):
        for _ in range(JUDGE_RUNS):
            verdict = judge(rounds, first=first)
            out[f"{first}_first"].append(
                {"winner": verdict["winner"], "margin": margin(verdict),
                 "scores": verdict["scores"]}  # per-criterion, to see what drives a win
            )
    return out


CHRONO_PATH = os.path.join("results", "chronological.json")


def chrono_path(model=None):
    """Where speaking-order results for a judge model live. The default
    judge (the debaters' own model) keeps the original file name."""
    if model is None or model == MODEL:
        return CHRONO_PATH
    return os.path.join("results", f"chronological_{model}.json")


def judge_in_speaking_order(debate, model=None):
    """Judge a saved debate JUDGE_RUNS times, listing sides as they spoke."""
    first = "bull" if debate["bull_first"] else "bear"
    runs = []
    for _ in range(JUDGE_RUNS):
        verdict = judge(debate["rounds"], first=first, model=model)
        runs.append({"winner": verdict["winner"], "margin": margin(verdict),
                     "scores": verdict["scores"]})
    return runs


def run_chronological(model=None):
    """Re-judge every saved debate of every variant. Skips finished ones."""
    path = chrono_path(model)
    results = load_results(path)
    for variant in VARIANTS:
        done = results.setdefault(variant, {})
        debate_paths = sorted(glob.glob(os.path.join(debate_dir(variant), "*.json")))
        for debate_path in debate_paths:  # not "path": that one is where results are saved
            with open(debate_path, encoding="utf-8") as f:
                debate = json.load(f)
            ticker = debate["ticker"]
            if ticker in done:
                print(f"{variant}/{ticker}: already done, skipping")
                continue
            print(f"\n=== {ticker} ({variant}, speaking order) ===")
            try:
                done[ticker] = judge_in_speaking_order(debate, model)
            except Exception as e:  # one bad reply should not stop the batch
                print(f"{variant}/{ticker}: FAILED ({type(e).__name__}: {e})")
            save_results(results, path)
    return results


def analyze_chronological(runs_by_ticker):
    """Summary of one setup judged in speaking order: {ticker: [run, ...]}."""
    runs = [r for rs in runs_by_ticker.values() for r in rs]
    if not runs:
        return None
    counts = Counter(r["winner"] for r in runs)
    unstable = sum(1 for rs in runs_by_ticker.values() if len({r["winner"] for r in rs}) > 1)
    return {
        "debates": len(runs_by_ticker),
        "judgments": len(runs),
        "counts": {k: counts.get(k, 0) for k in ("bull", "tie", "bear")},
        "mean_margin": round(sum(r["margin"] for r in runs) / len(runs), 2),
        "same_order_instability": round(unstable / len(runs_by_ticker), 3),
    }


def print_chronological(results):
    print("\n=== Judged in speaking order (nothing scrambled) ===")
    for variant in VARIANTS:
        s = analyze_chronological(results.get(variant, {}))
        if s is None:
            print(f"{variant}: no results yet")
            continue
        n, c = s["judgments"], s["counts"]
        print(f"{variant:11} {s['debates']} debates, {n} judgments: bull {c['bull'] / n:.0%}  "
              f"tie {c['tie'] / n:.0%}  bear {c['bear'] / n:.0%}   "
              f"mean margin {s['mean_margin']:+.2f}  self-disagreement {s['same_order_instability']:.0%}")


# Phase B rule, fixed before the run: if a different judge lowers the bear's
# share of judgments by at least DRIFT_BIG points, the judge's taste is a main
# driver; if it moves less than DRIFT_SMALL points, the judge is not the cause.
DRIFT_BIG = 20
DRIFT_SMALL = 10


def bear_share(runs_by_ticker):
    runs = [r for rs in runs_by_ticker.values() for r in rs]
    if not runs:
        return None
    return 100 * sum(1 for r in runs if r["winner"] == "bear") / len(runs)


def criterion_gaps(runs_by_ticker):
    """Mean bull-minus-bear score for each criterion (negative = bear ahead)."""
    runs = [r for rs in runs_by_ticker.values() for r in rs if r.get("scores")]
    if not runs:
        return None
    return {c: round(sum(r["scores"]["bull"][c] - r["scores"]["bear"][c] for r in runs) / len(runs), 2)
            for c in ("evidence", "logic", "responsiveness")}


def judge_verdict(shift_points):
    """Apply the pre-set rule to the drop in bear share (points)."""
    if shift_points >= DRIFT_BIG:
        return "judge-driven"
    if abs(shift_points) < DRIFT_SMALL:
        return "not judge-driven"
    return "inconclusive"


def compare_judges(base, other):
    """Compare two judges on the same debates.

    base and other look like chronological results: {variant: {ticker: [run, ...]}}.
    Returns bear share per setup and overall, the shift, the rule's verdict,
    and a per-company paired comparison (the debate is the real unit).
    """
    def pooled(results):
        return {t + "@" + v: rs for v, by in results.items() for t, rs in by.items()}

    out = {"setups": {}}
    for v in base:
        if v in other:
            a, b = bear_share(base[v]), bear_share(other.get(v, {}))
            if a is not None and b is not None:
                out["setups"][v] = {"base": round(a, 1), "other": round(b, 1)}
    pa, pb = pooled(base), pooled(other)
    both = sorted(set(pa) & set(pb))
    if not both:
        return None
    shares_a = bear_share({k: pa[k] for k in both})
    shares_b = bear_share({k: pb[k] for k in both})
    mean = lambda rs: sum(r["margin"] for r in rs) / len(rs)
    diffs = [mean(pb[k]) - mean(pa[k]) for k in both]  # positive = other judge likes bull more
    out.update({
        "debates": len(both),
        "bear_share_base": round(shares_a, 1),
        "bear_share_other": round(shares_b, 1),
        "shift_points": round(shares_a - shares_b, 1),
        "verdict": judge_verdict(shares_a - shares_b),
        "mean_margin_base": round(sum(mean(pa[k]) for k in both) / len(both), 2),
        "mean_margin_other": round(sum(mean(pb[k]) for k in both) / len(both), 2),
        "debates_other_kinder_to_bull": sum(1 for d in diffs if d > 0),
        "debates_other_harsher_on_bull": sum(1 for d in diffs if d < 0),
        "criterion_gaps_base": criterion_gaps({k: pa[k] for k in both}),
        "criterion_gaps_other": criterion_gaps({k: pb[k] for k in both}),
    })
    return out


def print_judge_comparison(base_name, other_name, c):
    if c is None:
        print("No debates judged by both judges yet.")
        return
    print(f"\n=== Judge comparison on the same {c['debates']} debates (speaking order) ===")
    print(f"bear share of judgments:  {base_name} {c['bear_share_base']:.0f}%   {other_name} {c['bear_share_other']:.0f}%"
          f"   (drop of {c['shift_points']:+.0f} points)")
    for v, x in c["setups"].items():
        print(f"  {v:11} {x['base']:.0f}% -> {x['other']:.0f}%")
    print(f"mean margin (bull minus bear, 30-pt scale):  {c['mean_margin_base']:+.2f} -> {c['mean_margin_other']:+.2f}")
    print(f"per debate: {other_name} kinder to bull in {c['debates_other_kinder_to_bull']}, "
          f"harsher in {c['debates_other_harsher_on_bull']}")
    print(f"bull-minus-bear by criterion: {c['criterion_gaps_base']} -> {c['criterion_gaps_other']}")
    print(f"rule (big >= {DRIFT_BIG} pts, small < {DRIFT_SMALL} pts): {c['verdict']}")


def load_results(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_results(results, path):
    os.makedirs("results", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def majority(winners):
    """Most common winner, or 'split' if no verdict has more than half the votes.

    'split' is not a tie the judge declared: it means the runs disagreed
    (for example bull, bear, tie once each).
    """
    (top, n), = Counter(winners).most_common(1)
    return top if n > len(winners) / 2 else "split"


def pair_verdict(a, b):
    """The swap-and-average fix: combine one run from each order.

    Adding the two margins cancels any bonus for being listed first, because
    each side was listed first exactly once.
    """
    total = a["margin"] + b["margin"]
    return "bull" if total > 0 else "bear" if total < 0 else "tie"


def analyze(results):
    ok = {t: r for t, r in results.items() if "bull_first" in r}
    n = len(ok)
    if n == 0:
        return None

    judgments = [(first, j["winner"]) for r in ok.values()
                 for first in ("bull", "bear") for j in r[f"{first}_first"]]
    decided = [(f, w) for f, w in judgments if w in ("bull", "bear")]

    # How often did the side listed FIRST win? 50% would mean no position effect.
    first_wins = sum(1 for f, w in decided if f == w)
    bull_wins = sum(1 for _, w in decided if w == "bull")

    # Did the majority verdict change when we only swapped the order? Only
    # debates with a clear majority in BOTH orders can show a flip; a split
    # (no majority) is counted separately instead of as a change.
    majorities = [
        (majority([j["winner"] for j in r["bull_first"]]),
         majority([j["winner"] for j in r["bear_first"]]))
        for r in ok.values()
    ]
    flips = sum(1 for a, b in majorities if "split" not in (a, b) and a != b)
    unclear = sum(1 for a, b in majorities if "split" in (a, b))

    # Baseline randomness: same order, repeated runs, not unanimous.
    def unstable(runs):
        return len({j["winner"] for j in runs}) > 1

    same_order_noise = sum(
        unstable(r[k]) for r in ok.values() for k in ("bull_first", "bear_first")
    ) / (2 * n)

    # The fix: pair run i of each order, add margins. Is it more stable?
    def fix_unstable(r):
        verdicts = {pair_verdict(a, b) for a, b in zip(r["bull_first"], r["bear_first"])}
        return len(verdicts) > 1

    # Continuous version, immune to ties: margin = bull points - bear points.
    # If listing a side first gives it a bonus, the margin is higher when bull
    # is first than when bear is first. Half that gap is the per-side bonus.
    def mean_margin(key):
        ms = [j["margin"] for r in ok.values() for j in r[key]]
        return sum(ms) / len(ms)

    first_bonus = (mean_margin("bull_first") - mean_margin("bear_first")) / 2

    return {
        "debates": n,
        "judgments": len(judgments),
        "first_position_bonus_points": round(first_bonus, 2),
        "first_listed_wins": round(first_wins / len(decided), 3) if decided else None,
        "bull_wins": round(bull_wins / len(decided), 3) if decided else None,
        "ties": len(judgments) - len(decided),
        "order_flip_rate": round(flips / n, 3),
        "unclear_majority_debates": unclear,
        "same_order_instability": round(same_order_noise, 3),
        "fixed_instability": round(sum(fix_unstable(r) for r in ok.values()) / n, 3),
    }


def print_report(results):
    summary = analyze(results)
    if summary is None:
        print("No completed debates yet.")
        return
    failed = [t for t, r in results.items() if "error" in r]
    s = summary
    print(f"\n=== Bias report: {s['debates']} debates, {s['judgments']} judgments ===")
    print(f"bonus for being listed FIRST:  {s['first_position_bonus_points']:+.2f} points (of 30; 0 = no position effect)")
    if s["first_listed_wins"] is not None and s["bull_wins"] is not None:
        print(f"side listed FIRST wins:        {s['first_listed_wins']:.0%}   (of decided verdicts; 50% = no position effect)")
        print(f"bull wins overall:             {s['bull_wins']:.0%}   (of decided verdicts; 50% = no side preference)")
    else:
        print("no judgment named a winner (all ties)")
    print(f"verdict flips when order swapped: {s['order_flip_rate']:.0%} of debates"
          f"   ({s['unclear_majority_debates']} debates had no clear majority in one order)")
    print(f"unstable even in SAME order:      {s['same_order_instability']:.0%}  (randomness baseline)")
    print(f"unstable with swap-and-average:   {s['fixed_instability']:.0%}  (the fix)")
    print(f"ties: {s['ties']}" + (f"   failed tickers: {', '.join(failed)}" if failed else ""))

    short = {"bull": "BULL", "bear": "bear", "tie": "tie"}
    print("\nticker   bull listed first         bear listed first")
    for t, r in results.items():
        if "bull_first" in r:
            bf = " ".join(f"{short[j['winner']]:4}" for j in r["bull_first"])
            rf = " ".join(f"{short[j['winner']]:4}" for j in r["bear_first"])
            print(f"{t:7}  {bf:24}  {rf}")


def main(args):
    # --variant NAME picks the experiment (default "base"); the rest are tickers.
    variant = "base"
    if "--variant" in args:
        i = args.index("--variant")
        variant = args[i + 1]
        args = args[:i] + args[i + 2:]
    if variant not in VARIANTS:
        sys.exit(f"Unknown variant {variant!r}. Choose from: {', '.join(VARIANTS)}")

    judge_model = None
    if "--judge-model" in args:
        i = args.index("--judge-model")
        judge_model = args[i + 1]
        args = args[:i] + args[i + 2:]

    if "--compare" in args:
        other = args[args.index("--compare") + 1]
        c = compare_judges(load_results(CHRONO_PATH), load_results(chrono_path(other)))
        print_judge_comparison(MODEL, other, c)
        return

    if "--chrono" in args:
        path = chrono_path(judge_model)
        results = load_results(path) if "--report" in args else run_chronological(judge_model)
        print_chronological(results)
        return

    path = results_path(variant)
    results = load_results(path)

    if "--report" in args:
        print_report(results)
        return

    # Note: the keys "bull_first"/"bear_first" inside results are which side the
    # JUDGE saw listed first. The variant controls who SPEAKS first in the debate.
    tickers = [a.upper() for a in args] or TICKERS
    for ticker in tickers:
        if ticker in results and "bull_first" in results[ticker]:
            print(f"{ticker}: already done, skipping")
            continue
        print(f"\n=== {ticker} ({variant}) ===")
        try:
            debate = run_debate(ticker, **VARIANTS[variant])
            save_debate(debate, debate_dir(variant))
            results[ticker] = judge_both_orders(debate["rounds"])
        except Exception as e:  # keep going; one bad filing shouldn't stop the batch
            print(f"{ticker}: FAILED ({type(e).__name__}: {e})")
            results[ticker] = {"error": f"{type(e).__name__}: {e}"}
        save_results(results, path)  # save after every ticker so a crash loses nothing

    print_report(results)


if __name__ == "__main__":
    main(sys.argv[1:])
