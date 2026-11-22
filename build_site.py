"""Build site/data.js from the saved debates and bias results.

Run locally after generating debates (it reads the cached filings in data/raw,
so it needs no network and no API key):

    python build_site.py

The site itself is static: site/index.html + site/style.css + site/app.js +
site/data.js. GitHub Actions only has to publish the site/ folder.
"""
import glob
import hashlib
import inspect
import json
import os
import re
import statistics as st
from datetime import datetime, timezone

from rapidfuzz import fuzz

import bias
import citations
import debate as debate_mod
from citations import MIN_WORDS, normalize, verify_quote
from fetch import (ITEM_1A_END, ITEM_1A_START, ITEM_7_END, ITEM_7_START,
                   extract_section, html_to_text)

REPO_URL = "https://github.com/TJA0308/Bull-vs-Bear"
OUT_PATH = os.path.join("site", "data.js")
CONTEXT_CHARS = 320  # filing text shown on each side of a quote

NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "TSLA": "Tesla",
    "AMZN": "Amazon", "GOOGL": "Alphabet", "META": "Meta", "NFLX": "Netflix",
    "AMD": "AMD", "ADBE": "Adobe", "CRM": "Salesforce", "COST": "Costco",
    "WMT": "Walmart", "KO": "Coca-Cola", "PEP": "PepsiCo", "NKE": "Nike",
}


def collapse(text):
    """Same steps as citations.normalize but keeps the original case,
    so match positions line up 1:1 and we can show readable context."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


_filing_cache = {}


def filing_text(ticker, accession):
    """The exact text the agents saw, rebuilt from the cached 10-K HTML.

    The accession number comes from the saved debate, so a newer 10-K cached
    later can never be mistaken for the one the agents read.
    """
    key = (ticker, accession)
    if key in _filing_cache:
        return _filing_cache[key]
    path = os.path.join("data", "raw", f"{ticker}_{accession}.html")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No cached filing {path}; run fetch.py {ticker} (and keep the same 10-K)")
    with open(path, encoding="utf-8") as f:
        text = html_to_text(f.read())
    combined = (
        "RISK FACTORS (Item 1A):\n" + extract_section(text, ITEM_1A_START, ITEM_1A_END)
        + "\n\nMANAGEMENT'S DISCUSSION AND ANALYSIS (Item 7):\n"
        + extract_section(text, ITEM_7_START, ITEM_7_END)
    )
    display = collapse(combined)
    norm = normalize(combined)
    _filing_cache[key] = (display, norm, combined)
    return _filing_cache[key]


def trim_to_words(s, from_left):
    """Drop a partial word at the cut edge."""
    if from_left:
        i = s.find(" ")
        return s[i + 1:] if 0 < i < 30 else s
    i = s.rfind(" ")
    return s[:i] if i > len(s) - 30 else s


def locate(quote, ticker, accession):
    """Where in the filing does this quote (approximately) appear?"""
    display, norm, _ = filing_text(ticker, accession)
    qn = normalize(quote)
    if len(display) != len(norm) or len(qn.split()) < MIN_WORDS:
        return None  # positions would not line up, or quote too short to place
    idx = norm.find(qn)
    if idx >= 0:
        start, end = idx, idx + len(qn)
    else:
        al = fuzz.partial_ratio_alignment(qn, norm)
        start, end = al.dest_start, al.dest_end
    pre = trim_to_words(display[max(0, start - CONTEXT_CHARS):start], True)
    post = trim_to_words(display[end:end + CONTEXT_CHARS], False)
    return {"pre": pre, "match": display[start:end], "post": post}


def slim_debate(d):
    """Keep what the page needs; attach filing context to each quote."""
    rounds = []
    for r in d["rounds"]:
        entry = {"round": r["round"]}
        for side in ("bull", "bear"):
            turn = r[side]
            claims = []
            for c in turn["claims"]:
                claims.append({
                    "claim": c.get("claim", ""),
                    "quote": c.get("quote", ""),
                    "verified": c["verified"],
                    "score": c["score"],
                    "ctx": locate(c.get("quote", ""), d["ticker"], d["filing"]["accession"]),
                })
            entry[side] = {"argument": turn["argument"], "claims": claims}
        rounds.append(entry)
    return {
        "ticker": d["ticker"],
        "name": NAMES.get(d["ticker"], d["ticker"]),
        "filingDate": d["filing"]["date"],
        "accession": d["filing"]["accession"],
        "model": d["model"],
        "bullFirst": d["bull_first"],
        "rounds": rounds,
        "citations": d["citations"],
        "judge": d["judge"],
        "usage": d["usage"],
    }


def load_debates(folder):
    out = {}
    for p in sorted(glob.glob(os.path.join(folder, "*.json"))):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        out[d["ticker"]] = slim_debate(d)
    return out


# ---- checker experiment ------------------------------------------------

def stable_int(*parts):
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16)


def swap_one_word(q):
    words = q.split()
    i = stable_int(q) % len(words)
    words[i] = "zebra"
    return " ".join(words)


def drop_two_words(q):
    words = q.split()
    m = len(words) // 2
    return " ".join(words[:m] + words[m + 2:])


def change_one_number(q):
    """Change the last digit of the first number; None if the quote has no number."""
    m = citations.NUMBER.search(q)
    if not m:
        return None
    digits = m.group(0)
    last = int(digits[-1]) if digits[-1].isdigit() else None
    if last is None:
        return None
    return q[:m.start()] + digits[:-1] + str((last + 3) % 10) + q[m.end():]


def checker_experiment(debates):
    tickers = list(debates)
    rows = {"real": [], "swap": [], "drop": [], "number": [], "wrong": []}
    short = 0
    for t in tickers:
        _, _, combined = filing_text(t, debates[t]["accession"])
        other = tickers[(tickers.index(t) + 1) % len(tickers)]
        _, _, other_text = filing_text(other, debates[other]["accession"])
        for r in debates[t]["rounds"]:
            for side in ("bull", "bear"):
                for c in r[side]["claims"]:
                    q = c["quote"]
                    if len(q.split()) < MIN_WORDS:
                        short += 1
                        continue
                    label = q if len(q) <= 150 else q[:147] + "..."
                    variants = {
                        "real": (q, combined), "swap": (swap_one_word(q), combined),
                        "drop": (drop_two_words(q), combined), "wrong": (q, other_text),
                    }
                    changed = change_one_number(q)
                    if changed:
                        variants["number"] = (changed, combined)
                    for kind, (text, source) in variants.items():
                        if len(text.split()) < MIN_WORDS:
                            continue  # would fail the length rule, not the match; not informative
                        ok, score = verify_quote(text, source)
                        rows[kind].append({"t": t, "s": round(score, 1), "v": ok,
                                           "q": text if len(text) <= 150 else text[:147] + "..."})
    return {"rows": rows, "tooShort": short, "threshold": 90}


# ---- bias results ------------------------------------------------------

# Two-sided 95% t critical values by degrees of freedom (n - 1). With only
# ~16 debates, 1.96 would make the range too narrow.
T_95 = {5: 2.571, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
        14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086}


def variant_summary(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        results = json.load(f)
    ok = {t: r for t, r in results.items() if "bull_first" in r}
    if not ok:
        return None
    summary = bias.analyze(results)

    counts = {"bull": 0, "bear": 0, "tie": 0}
    for r in ok.values():
        for k in ("bull_first", "bear_first"):
            for j in r[k]:
                counts[j["winner"]] += 1

    # Per-debate position bonus: half the margin gap between the two listing orders.
    bonuses = []
    for r in ok.values():
        mb = st.mean(j["margin"] for j in r["bull_first"])
        mr = st.mean(j["margin"] for j in r["bear_first"])
        bonuses.append((mb - mr) / 2)
    mean_b = st.mean(bonuses)
    se = st.stdev(bonuses) / len(bonuses) ** 0.5 if len(bonuses) > 1 else 0.0
    crit = T_95.get(len(bonuses) - 1, 1.96)  # small samples need a wider range than 1.96

    rows = {t: {"bullListedFirst": [{"w": j["winner"], "m": j["margin"]} for j in r["bull_first"]],
                "bearListedFirst": [{"w": j["winner"], "m": j["margin"]} for j in r["bear_first"]]}
            for t, r in ok.items()}
    failed = {t: r["error"] for t, r in results.items() if "error" in r}
    return {"summary": summary, "counts": counts, "bonusMean": round(mean_b, 2),
            "bonusLo": round(mean_b - crit * se, 2), "bonusHi": round(mean_b + crit * se, 2),
            "rows": rows, "failed": failed}


def chronological_summary():
    """Both setups re-judged in speaking order (bias.py --chrono), or None."""
    results = bias.load_results(bias.CHRONO_PATH)
    out = {"base": bias.analyze_chronological(results.get("base", {})),
           "bearFirst": bias.analyze_chronological(results.get("bear-first", {}))}
    return out if out["base"] and out["bearFirst"] else None


def parse_prompts():
    return {
        "bull": debate_mod.SIDE_PROMPTS["bull"],
        "bear": debate_mod.SIDE_PROMPTS["bear"],
        "outputFormat": debate_mod.OUTPUT_FORMAT,
        "judge": debate_mod.JUDGE_SYSTEM,
    }


def main():
    base = load_debates("debates")
    variant = load_debates(os.path.join("debates", "variants", "bear-first"))

    quotes = sum(d["citations"]["overall"]["total"] for d in base.values())
    verified = sum(d["citations"]["overall"]["verified"] for d in base.values())
    cost = sum(d["usage"]["cost_usd"] for d in base.values())
    n_calls = sum(d["usage"]["calls"] for d in base.values())
    tokens_in = sum(d["usage"]["input_tokens"] for d in base.values())

    data = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": REPO_URL,
        "model": next(iter(base.values()))["model"],
        "meta": {
            "debates": len(base), "quotes": quotes, "verified": verified,
            "costPerDebate": round(cost / len(base), 4), "callsPerDebate": round(n_calls / len(base)),
            "tokensInPerDebate": round(tokens_in / len(base)),
        },
        "debates": {"base": base, "bearFirst": variant},
        "bias": {"base": variant_summary(bias.results_path("base")),
                 "bearFirst": variant_summary(bias.results_path("bear-first")),
                 "chrono": chronological_summary()},
        "checker": checker_experiment(base),
        "prompts": parse_prompts(),
        "code": {"verify": inspect.getsource(citations.verify_quote),
                 "normalize": inspect.getsource(citations.normalize)},
    }

    os.makedirs("site", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("// Generated by build_site.py. Do not edit by hand.\n")
        f.write("window.SITE_DATA = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    kb = os.path.getsize(OUT_PATH) / 1024
    print(f"wrote {OUT_PATH} ({kb:,.0f} KB): {len(base)} base debates, "
          f"{len(variant)} bear-first debates, {quotes} quotes")
    for name, key in (("base", "base"), ("bear-first", "bearFirst")):
        b = data["bias"][key]
        print(f"bias[{name}]:", "none yet" if b is None else f"{b['summary']['debates']} debates, counts {b['counts']}")
    ck = data["checker"]["rows"]
    print("checker rows:", {k: len(v) for k, v in ck.items()}, "short quotes skipped:", data["checker"]["tooShort"])


if __name__ == "__main__":
    main()
