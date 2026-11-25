"""Claim-support check: does a verified quote actually back up the claim built on it?

The code checker (citations.py) proves a quote's WORDS appear in the filing. It
cannot tell whether those words support the claim that cites them. This module
adds a second, weaker layer: one cheap Haiku call per claim/quote pair that
answers yes / partly / no. Because an LLM can be wrong, the layer is only kept
if it agrees with a human on a hand-labelled sample.

Labels (the same wording is given to the human labeller and to the model):

  yes     the quote states, or directly implies, what the claim says, including
          its numbers and its direction (up/down).
  partly  the quote is on topic and backs part of the claim, but the claim goes
          beyond it: a number, a cause, a size or a "largest/most" that the
          quote does not contain.
  no      the quote does not say this, or says something different or the
          opposite.

DECISION RULE, fixed BEFORE any model call is made on the sample (committed first,
so git history shows it):

  Sample: 40 claim/quote pairs, built by `python claim_support.py sample`:
    30 real pairs (verified quote, the claim that cited it), at most 2 per company;
    10 mismatched pairs (a real claim with a real, verified quote taken from a
    different claim: 5 from another company, 5 from the same company).
  Truth for every pair is the human's label, not how the pair was built.
  The human labels the sheet BEFORE seeing any model output.

  A = share of the 40 where the model's label equals the human's (3 levels).
  B = share where model and human agree on "supported at all" (yes or partly)
      versus "no".
  M = of the pairs the human labelled "no", the share the model called yes or partly.

  KEEP the layer (show it on the site) only if ALL THREE hold:
      A >= 70%     B >= 85%     M <= 20%
  otherwise DROP it from the site and report the numbers anyway.

  Why these numbers: with 40 pairs a share is good to about +/-13 points, so
  anything much below 70% on 3 levels is not distinguishable from guessing
  between neighbouring labels; B is stricter because "no" is the case that
  matters (a quote that does not back the claim); M caps the misses. They are
  set before any model output exists and are not tuned afterwards. The "always
  say yes" baseline is reported next to them so a pass has to beat it.

Cost: about 40 calls of a few hundred tokens each, well under $0.05 at Haiku
prices. Running it on all 190 verified claims is under $0.20.

Usage:
    python claim_support.py sample    # write the label sheet (no API calls)
    python claim_support.py run       # run the model on the labelled sample, then report
    python claim_support.py --report  # analyze saved results, no API calls
"""
import csv
import glob
import json
import os
import random
import sys

from llm import ask_llm, parse_json, totals

DEBATE_DIR = "debates"
SAMPLE_PATH = os.path.join("results", "claim_support_sample.json")
LABELS_PATH = os.path.join("results", "claim_support_labels.csv")
RUN_PATH = os.path.join("results", "claim_support_run.json")

N_REAL = 30
N_MISMATCHED = 10          # half from another company, half from the same company
MAX_PER_COMPANY = 2
SEED = 7
COST_CAP = 0.50            # dollars

LABELS = ("yes", "partly", "no")
MIN_AGREE_3 = 0.70         # A
MIN_AGREE_BINARY = 0.85    # B
MAX_MISS = 0.20            # M

SYSTEM = """You check whether a quote from a company's SEC filing supports a claim made about it.
Judge only from the quote: do not use outside knowledge, and do not give credit for what the quote might imply in other places.

Reply with ONLY a JSON object:
{"verdict": "yes" | "partly" | "no", "reason": "one short sentence"}

yes     the quote states, or directly implies, what the claim says, including its numbers and its direction (up or down).
partly  the quote is on topic and backs part of the claim, but the claim goes beyond it: a number, a cause, a size, or a "largest" or "most" that the quote does not contain.
no      the quote does not say this, or says something different or the opposite."""


# --- building the sample ---

def load_pairs(debate_dir=DEBATE_DIR):
    """Every verified claim/quote pair in the saved base debates (not the variants)."""
    pairs = []
    for path in sorted(glob.glob(os.path.join(debate_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            debate = json.load(f)
        for rnd in debate["rounds"]:
            for side in ("bull", "bear"):
                for i, c in enumerate(rnd[side]["claims"]):
                    if c.get("verified"):
                        pairs.append({"ticker": debate["ticker"], "round": rnd["round"], "side": side,
                                      "index": i, "claim": c["claim"], "quote": c["quote"]})
    return pairs


def build_sample(pairs, seed=SEED, n_real=N_REAL, n_mismatched=N_MISMATCHED):
    """Pick real pairs, then build mismatched ones from unused pairs.

    Returns a list of dicts (id P01.., claim, quote, built_as, source), shuffled so the
    labeller cannot tell real from mismatched by position."""
    rng = random.Random(seed)
    by_ticker = {}
    for p in pairs:
        by_ticker.setdefault(p["ticker"], []).append(p)
    real = []
    for ticker in sorted(by_ticker):
        pool = by_ticker[ticker][:]
        rng.shuffle(pool)
        real.extend(pool[:MAX_PER_COMPANY])
    rng.shuffle(real)
    real = real[:n_real]
    used = {id(p) for p in real}
    spare = [p for p in pairs if id(p) not in used]
    rng.shuffle(spare)

    half = n_mismatched // 2
    wants = ["other_company"] * half + ["same_company"] * (n_mismatched - half)
    mismatched = []
    for want in wants:
        claim_p = spare.pop()
        pick = next((q for q in spare if (q["ticker"] != claim_p["ticker"]) == (want == "other_company")
                     and q["quote"] != claim_p["quote"]), None)
        if pick is None:
            raise ValueError(f"cannot build a {want} mismatch from the remaining pairs")
        spare.remove(pick)
        mismatched.append({"ticker": claim_p["ticker"], "claim": claim_p["claim"], "quote": pick["quote"],
                           "built_as": f"mismatch_{want}",
                           "source": {"claim_from": _ref(claim_p), "quote_from": _ref(pick)}})
    items = [{"ticker": p["ticker"], "claim": p["claim"], "quote": p["quote"], "built_as": "real",
              "source": {"claim_from": _ref(p), "quote_from": _ref(p)}} for p in real] + mismatched
    rng.shuffle(items)
    for n, item in enumerate(items, 1):
        item["id"] = f"P{n:02d}"
    return items


def _ref(p):
    return f"{p['ticker']} round {p['round']} {p['side']} claim {p['index'] + 1}"


def write_label_sheet(items, path=LABELS_PATH):
    """A CSV the human fills in: id, claim, quote, label (blank). utf-8-sig so Excel reads it."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "claim", "quote", "label"])
        for it in items:
            w.writerow([it["id"], it["claim"], it["quote"], ""])


def read_labels(path=LABELS_PATH):
    """{id: label}. Raises ValueError listing every row that is blank or not yes/partly/no."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    labels, bad = {}, []
    for row in rows:
        label = (row.get("label") or "").strip().lower()
        if label in LABELS:
            labels[row["id"]] = label
        else:
            bad.append(row["id"])
    if bad:
        raise ValueError(f"label must be yes, partly or no; fix these rows: {', '.join(bad)}")
    return labels


# --- the model check ---

def check_support(claim, quote, model=None):
    """One model call. Returns {"verdict": yes|partly|no, "reason": str}."""
    messages = [{"role": "user", "content": f"CLAIM: {claim}\n\nQUOTE: {quote}"}]
    for attempt in range(2):
        reply = ask_llm(SYSTEM, messages, max_tokens=300, model=model)
        try:
            out = parse_json(reply)
            verdict = str(out.get("verdict", "")).strip().lower()
            if verdict in LABELS:
                return {"verdict": verdict, "reason": str(out.get("reason", "")).strip()}
        except ValueError:
            pass
        messages = messages + [{"role": "assistant", "content": reply},
                               {"role": "user", "content": 'Reply with ONLY {"verdict": "yes"|"partly"|"no", "reason": "..."}.'}]
    raise ValueError("model did not return a valid verdict twice")


# --- scoring ---

def score(human, model):
    """Agreement numbers for {id: label} human and model. Only ids in both count."""
    ids = sorted(set(human) & set(model))
    n = len(ids)
    if n == 0:
        return None
    supported = lambda label: label != "no"
    a = sum(human[i] == model[i] for i in ids) / n
    b = sum(supported(human[i]) == supported(model[i]) for i in ids) / n
    no_ids = [i for i in ids if human[i] == "no"]
    miss = (sum(supported(model[i]) for i in no_ids) / len(no_ids)) if no_ids else None
    baseline = sum(supported(human[i]) for i in ids) / n  # always say "yes" is right this often on B
    return {"n": n, "agree_3": a, "agree_binary": b, "miss_rate": miss, "n_human_no": len(no_ids),
            "baseline_binary": baseline,
            "confusion": {h: {m: sum(1 for i in ids if human[i] == h and model[i] == m) for m in LABELS}
                          for h in LABELS}}


def decide(s):
    """The pre-set rule. Returns "keep" or "drop" (or "not enough data")."""
    if s is None or s["miss_rate"] is None:
        return "not enough data"
    ok = (s["agree_3"] >= MIN_AGREE_3 and s["agree_binary"] >= MIN_AGREE_BINARY
          and s["miss_rate"] <= MAX_MISS)
    return "keep" if ok else "drop"


def print_report(s):
    if s is None:
        print("Nothing to report yet.")
        return
    pct = lambda x: "n/a" if x is None else f"{100 * x:.0f}%"
    print(f"\n=== Claim-support check vs hand labels ({s['n']} pairs) ===")
    print(f"A  3-level agreement (yes/partly/no):  {pct(s['agree_3'])}   (needs >= {pct(MIN_AGREE_3)})")
    print(f"B  supported-at-all agreement:         {pct(s['agree_binary'])}   (needs >= {pct(MIN_AGREE_BINARY)};"
          f" 'always yes' would score {pct(s['baseline_binary'])})")
    print(f"M  human 'no' pairs the model let through: {pct(s['miss_rate'])} of {s['n_human_no']}"
          f"   (needs <= {pct(MAX_MISS)})")
    print("rows = human label, columns = model label")
    print("          " + "".join(f"{m:>8}" for m in LABELS))
    for h in LABELS:
        print(f"  {h:8}" + "".join(f"{s['confusion'][h][m]:>8}" for m in LABELS))
    print(f"rule: {decide(s)}")


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def report():
    human = read_labels() if os.path.exists(LABELS_PATH) else {}
    model = {k: v["verdict"] for k, v in load_json(RUN_PATH).items()}
    print_report(score(human, model))


def run():
    sample = load_json(SAMPLE_PATH)
    if not sample:
        sys.exit("No sample yet. Run: python claim_support.py sample")
    human = read_labels()  # refuses to run until every row is labelled
    done = load_json(RUN_PATH)
    for item in sample:
        if item["id"] in done:
            continue
        if totals["cost"] > COST_CAP:
            print(f"Stopping: cost ${totals['cost']:.2f} passed the ${COST_CAP:.2f} cap.")
            break
        done[item["id"]] = check_support(item["claim"], item["quote"])
        os.makedirs("results", exist_ok=True)
        with open(RUN_PATH, "w", encoding="utf-8") as f:
            json.dump(done, f, indent=2)
    print(f"\ncost this run: ${totals['cost']:.4f} over {totals['calls']} calls")
    print_report(score(human, {k: v["verdict"] for k, v in done.items()}))


def make_sample():
    if os.path.exists(LABELS_PATH) and any(
            (r.get("label") or "").strip() for r in csv.DictReader(open(LABELS_PATH, encoding="utf-8-sig"))):
        sys.exit(f"{LABELS_PATH} already has labels; not overwriting it.")
    items = build_sample(load_pairs())
    os.makedirs("results", exist_ok=True)
    with open(SAMPLE_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    write_label_sheet(items)
    kinds = {}
    for it in items:
        kinds[it["built_as"]] = kinds.get(it["built_as"], 0) + 1
    print(f"wrote {len(items)} pairs {kinds}\n  sheet for you: {LABELS_PATH}\n  key (do not open until labelled): {SAMPLE_PATH}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sample":
        make_sample()
    elif cmd == "run":
        run()
    elif cmd == "--report":
        report()
    else:
        sys.exit("Usage: python claim_support.py sample | run | --report")
