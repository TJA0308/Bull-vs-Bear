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
"""
import json
import os
import sys
from collections import Counter

from debate import judge, run_debate, save_debate

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
    """Most common winner; 'tie' if there is no clear majority."""
    (top, n), = Counter(winners).most_common(1)
    return top if n > len(winners) / 2 else "tie"


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

    # Did the majority verdict change when we only swapped the order?
    flips = sum(
        1 for r in ok.values()
        if majority([j["winner"] for j in r["bull_first"]])
        != majority([j["winner"] for j in r["bear_first"]])
    )

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
        "bull_wins": round(bull_wins / len(decided), 3),
        "ties": len(judgments) - len(decided),
        "order_flip_rate": round(flips / n, 3),
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
    if s["first_listed_wins"] is not None:
        print(f"side listed FIRST wins:        {s['first_listed_wins']:.0%}   (of decided verdicts; 50% = no position effect)")
        print(f"bull wins overall:             {s['bull_wins']:.0%}   (of decided verdicts; 50% = no side preference)")
    print(f"verdict flips when order swapped: {s['order_flip_rate']:.0%} of debates")
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
