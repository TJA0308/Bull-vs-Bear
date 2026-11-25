"""Phase D: repeat the debates so the bear's edge and the input effect can be read.

Phase C found that one debate per company is too noisy: regenerating the same
input moved the bear's share of judgments from 71% to 42%. So here each
condition gets 5 independent DRAWS. A draw is one freshly generated debate for
each of the 16 companies (bull speaks first, 2 rounds), each judged 3 times in
speaking order by Haiku 5.5, the same judge as Phase C.

  full      5 draws of the full input (all of Items 1A and 7):
            the saved original and the Phase C rerun, plus 3 new draws.
  balanced  5 draws of the balanced input (first 2,500 words of each section):
            the Phase C balanced draw, plus 4 new draws.

New draws are named full-3, full-4, full-5 and balanced-2 .. balanced-5.

DECISION RULE, fixed BEFORE any paid run (committed first, so git history shows it):

  Score of a draw = the mean margin over all its 48 judgments
  (bull score minus bear score, 30-point scale; negative = the bear is ahead).
  The draw is the unit, not the judgment, because the judgments of one debate
  and of one draw are not independent.
  Only draws with all 16 companies count. Draws are never added or dropped
  after seeing results; a company that failed is re-run until the draw is full.

  Question 1, how big is the bear's edge on full input?
    m_F = mean of the 5 full-draw scores, s_F their standard deviation,
    interval = m_F +/- t * s_F / sqrt(5)   (95%, t = 2.776 for 4 degrees of freedom).
      interval entirely below 0   -> "bear edge confirmed" (report m_F and the interval)
      interval includes 0         -> "no clear edge"
      interval entirely above 0   -> "bull edge"

  Question 2, does balancing the input change the margin?
    E  = mean of the 5 balanced scores minus m_F   (positive = balancing helps the bull)
    SE = sqrt(s_F^2/5 + s_B^2/5);  H = t * SE, a 95% Welch interval half-width, with
    t from the Welch degrees of freedom rounded DOWN (the wider, safer value).
      H > 1.0 point                          -> "too noisy to read"
      else |E| >= 1.0 and the interval E +/- H excludes 0   -> "input-driven"
      else E +/- H lies entirely inside (-1.0, +1.0)         -> "not input-driven"
      else                                   -> "inconclusive"

  Why 1.0 point: about half of the bear's lead seen so far (-1.4 to -2.0 on the
  30-point scale), so an effect smaller than that could not explain the lead.
  Calibration, stated honestly: the 1.0 was chosen after seeing the three
  Phase C draws. Their draw-to-draw spread (about 0.4 points per 16-company
  mean) implies H of about 0.6 with 5 draws each, so the question can be
  answered; if the new draws are noisier than that, the rule says "too noisy".

  Descriptive only, no rule: each draw's bear share of judgments and its score,
  how often the bull wins at all, and whether the same companies lean bear
  across draws (rank correlation of per-company scores).

Cost: 3 full draws plus 4 balanced draws, about $1.50 (Phase C cost $0.47 for one
full and one balanced draw). The run stops before starting another draw once it has spent $2.50.

RESULT (run 2026-11-24; 7 new draws of 16 companies; $1.53 over 897 calls, 0 failures):

  Draw scores (mean margin, 30-point scale):
    full      -1.96 -1.40 -2.04 -1.81 -2.25   (mean -1.89, sd 0.32)
    balanced  -1.88 -2.54 -1.85 -1.46 -1.81   (mean -1.91, sd 0.39)
  Bear share of judgments per draw: full 71 42 62 62 69, balanced 58 73 56 54 62.
  Bull share: 0 to 10% in every draw.

  Question 1: -1.89 +/- 0.40 -> "bear edge confirmed" (the interval is entirely
  below 0), for Haiku as the judge, bull speaking first.
  Question 2: balanced minus full = -0.02 +/- 0.54 -> "not input-driven". The
  half-width 0.54 is under 1.0, so the question was readable, and the interval
  lies inside (-1, +1). Giving the debaters equal-size chunks of Risk Factors and
  MD&A did not change the margin by anything near the 1-point size that matters.

  Descriptive: single-draw bear shares spread by about 8 to 11 points (sd) across
  draws of the same input, with a range of 42 to 73, so a share from one draw is
  good to roughly +/-15 points. Per-company rank agreement across full draws was
  only +0.18, so which companies lean bear is mostly chance at this depth.

  What this does NOT show: the edge is specific to the Haiku judge (Sonnet scored
  the original debates at +0.12, a slight bull lead, in Phase B), and the bear-first
  setup was not repeated.

Usage:
    python phase_d.py                 # run the 7 new draws (about $1.50), then report
    python phase_d.py full-3          # run one new draw
    python phase_d.py --report        # analyze saved results, no API calls
"""
import json
import os
import statistics as st
import sys

from bias import CHRONO_PATH, TICKERS, load_results
from llm import totals
import phase_c

RESULTS_PATH = os.path.join("results", "phase_d.json")
COST_CAP = 2.50          # dollars; the run stops before starting a draw past this
N_COMPANIES = len(TICKERS)
EFFECT_POINTS = 1.0      # the pre-set size that matters, in margin points of 30

NEW_DRAWS = {
    "full-3": "full", "full-4": "full", "full-5": "full",
    "balanced-2": "balanced", "balanced-3": "balanced",
    "balanced-4": "balanced", "balanced-5": "balanced",
}

# Two-sided 95% t critical values by degrees of freedom.
T_975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
         8: 2.306, 9: 2.262, 10: 2.228}


def t_crit(df):
    """95% t value; beyond the table use 2.0 (slightly narrower than 2.228 but fine for df > 10)."""
    return T_975.get(int(df), 2.0 if df > 10 else 12.706)


def draw_dir(name):
    return os.path.join("debates", "variants", f"phase-d-{name}")


def draw_score(draw):
    """Mean margin over every judgment in a draw ({ticker: [run, ...]})."""
    margins = [r["margin"] for rs in draw.values() for r in rs]
    return sum(margins) / len(margins)


def draw_bear_share(draw):
    runs = [r for rs in draw.values() for r in rs]
    return sum(1 for r in runs if r["winner"] == "bear") / len(runs)


def is_full(draw):
    return len(draw) >= N_COMPANIES and all(len(rs) > 0 for rs in draw.values())


def load_draws():
    """{"full": [draw, ...], "balanced": [draw, ...]}, complete draws only.
    Order: the saved original / Phase C draws first, then the new draws."""
    c = load_results(phase_c.RESULTS_PATH)
    new = load_results(RESULTS_PATH)
    full = [load_results(CHRONO_PATH).get("base", {}), c.get("rerun", {})]
    balanced = [c.get("balanced", {})]
    for name, kind in NEW_DRAWS.items():
        (full if kind == "full" else balanced).append(new.get(name, {}))
    return {"full": [d for d in full if is_full(d)], "balanced": [d for d in balanced if is_full(d)]}


def mean_ci(scores):
    """(mean, half-width of the 95% interval) over draw scores."""
    n = len(scores)
    m = st.mean(scores)
    if n < 2:
        return m, None
    return m, t_crit(n - 1) * st.stdev(scores) / n ** 0.5


def welch(a, b):
    """(difference of means b - a, 95% half-width) with Welch degrees of freedom rounded down."""
    va, vb = st.variance(a) / len(a), st.variance(b) / len(b)
    se = (va + vb) ** 0.5
    if se == 0:
        return st.mean(b) - st.mean(a), 0.0
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    return st.mean(b) - st.mean(a), t_crit(max(1, int(df))) * se


def edge_verdict(full_scores):
    """Question 1 of the pre-set rule."""
    m, h = mean_ci(full_scores)
    if h is None:
        return "not enough draws"
    if m + h < 0:
        return "bear edge confirmed"
    if m - h > 0:
        return "bull edge"
    return "no clear edge"


def input_verdict(full_scores, balanced_scores):
    """Question 2 of the pre-set rule."""
    if len(full_scores) < 2 or len(balanced_scores) < 2:
        return "not enough draws"
    e, h = welch(full_scores, balanced_scores)
    if h > EFFECT_POINTS:
        return "too noisy to read"
    if abs(e) >= EFFECT_POINTS and (e - h > 0 or e + h < 0):
        return "input-driven"
    if e - h > -EFFECT_POINTS and e + h < EFFECT_POINTS:
        return "not input-driven"
    return "inconclusive"


def analyze(draws):
    full = [draw_score(d) for d in draws["full"]]
    bal = [draw_score(d) for d in draws["balanced"]]
    out = {"n_full": len(full), "n_balanced": len(bal), "full_scores": full, "balanced_scores": bal,
           "edge": edge_verdict(full), "input": input_verdict(full, bal)}
    if full:
        out["full_mean"], out["full_half"] = mean_ci(full)
    if bal:
        out["balanced_mean"], out["balanced_half"] = mean_ci(bal)
    if len(full) >= 2 and len(bal) >= 2:
        out["effect"], out["effect_half"] = welch(full, bal)
    out["bear_share"] = {k: [round(100 * draw_bear_share(d)) for d in v] for k, v in draws.items()}
    out["bull_share"] = {k: [round(100 * sum(1 for rs in d.values() for r in rs if r["winner"] == "bull")
                                   / sum(len(rs) for rs in d.values())) for d in v] for k, v in draws.items()}
    per_company = [[st.mean(r["margin"] for r in d[t]) for t in sorted(d)] for d in draws["full"]]
    agree = [phase_c.spearman(per_company[i], per_company[j])
             for i in range(len(per_company)) for j in range(i + 1, len(per_company))]
    agree = [a for a in agree if a is not None]
    out["company_agreement"] = round(st.mean(agree), 2) if agree else None
    return out


def print_report(a):
    print(f"\n=== Phase D: {a['n_full']} full draws, {a['n_balanced']} balanced draws "
          f"({N_COMPANIES} companies each) ===")
    fmt = lambda xs: ", ".join(f"{x:+.2f}" for x in xs)
    print(f"draw scores, full:     {fmt(a['full_scores'])}")
    print(f"draw scores, balanced: {fmt(a['balanced_scores'])}")
    print(f"bear share per draw, full: {a['bear_share']['full']}   balanced: {a['bear_share']['balanced']}")
    print(f"bull share per draw, full: {a['bull_share']['full']}   balanced: {a['bull_share']['balanced']}")
    if "full_half" in a and a["full_half"] is not None:
        print(f"Q1 bear's edge on full input: {a['full_mean']:+.2f} +/- {a['full_half']:.2f}  -> {a['edge']}")
    else:
        print(f"Q1: {a['edge']}")
    if "effect" in a:
        print(f"Q2 balanced minus full: {a['effect']:+.2f} +/- {a['effect_half']:.2f}  -> {a['input']}")
    else:
        print(f"Q2: {a['input']}")
    ag = a["company_agreement"]
    print("same-company agreement across full draws (mean rank correlation): " + ("n/a" if ag is None else f"{ag:+.2f}"))
    print(f"rule: Q2 needs half-width <= {EFFECT_POINTS} to be read; effect size that counts: {EFFECT_POINTS} points")


def report():
    print_report(analyze(load_draws()))


def run_draw(name):
    phase_c.run_condition(name, results_path=RESULTS_PATH, out_dir=draw_dir(name),
                          input_mode=NEW_DRAWS[name])


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--report" in args:
        report()
        sys.exit()
    names = [a for a in args if not a.startswith("-")] or list(NEW_DRAWS)
    unknown = [n for n in names if n not in NEW_DRAWS]
    if unknown:
        sys.exit(f"Unknown draw {unknown[0]!r}. Choose from: {', '.join(NEW_DRAWS)}")
    for name in names:
        if totals["cost"] > COST_CAP:
            print(f"Stopping before {name}: cost ${totals['cost']:.2f} passed the ${COST_CAP:.2f} cap.")
            break
        run_draw(name)
    print(f"\ncost this run: ${totals['cost']:.4f} over {totals['calls']} calls")
    report()
