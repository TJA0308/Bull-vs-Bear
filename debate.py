"""Bull vs. bear debate over a 10-K, scored by a judge.

Usage: python debate.py AAPL [rounds]
Writes debates/AAPL.json
"""
import json
import os
import sys
from datetime import datetime, timezone

from citations import verify_quote
from fetch import get_sections
from llm import MODEL, ask_llm, parse_json, totals

DEBATE_DIR = "debates"

OUTPUT_FORMAT = """Reply with ONLY a JSON object and nothing else:
{
  "argument": "your argument, 100-180 words",
  "claims": [
    {"claim": "one specific point", "quote": "a VERBATIM quote of 8-40 words copied exactly from the filing excerpts"}
  ]
}
Give 2 or 3 claims. Each quote must be copied word for word from the filing
excerpts. Never paraphrase inside a quote and never invent one."""

SIDE_PROMPTS = {
    "bull": (
        "You are the BULL analyst in a debate about {ticker}. Argue that the "
        "company is a strong investment. Use ONLY the filing excerpts you are "
        "given; do not use outside knowledge or invent numbers. Be persuasive "
        "but honest: if the filing contradicts you, address it."
    ),
    "bear": (
        "You are the BEAR analyst in a debate about {ticker}. Argue that the "
        "company is a risky or poor investment. Use ONLY the filing excerpts "
        "you are given; do not use outside knowledge or invent numbers. Be "
        "persuasive but honest: if the filing contradicts you, address it."
    ),
}

JUDGE_SYSTEM = """You are an impartial judge of a bull vs. bear debate about a stock.
You see the transcript. Next to every quote, code has checked whether it really
appears in the company's filing. A claim whose quote is NOT VERIFIED is weak
evidence and must count against that side.

Score each side from 1 to 10 on:
- evidence: specific, accurate, verified quotes that support the claims
- logic: sound reasoning from that evidence
- responsiveness: answers the opponent's strongest points

Do not reward length. Do not favor a side for speaking first or last.
Reply with ONLY a JSON object:
{
  "scores": {
    "bull": {"evidence": 0, "logic": 0, "responsiveness": 0},
    "bear": {"evidence": 0, "logic": 0, "responsiveness": 0}
  },
  "winner": "bull" or "bear" or "tie",
  "reasoning": "2-3 sentences"
}"""


def parse_turn(reply):
    """Parse a debater's reply and check its shape.

    Raises ValueError (so the caller can retry) if the JSON is bad or a claim
    lacks text for "claim" or "quote". Without this, a null quote would crash
    the citation checker after the model calls were already paid for.
    """
    turn = parse_json(reply)
    if not isinstance(turn.get("argument"), str):
        raise ValueError('"argument" must be a string')
    claims = turn.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError('"claims" must be a non-empty list')
    for c in claims:
        if not (isinstance(c, dict) and isinstance(c.get("claim"), str) and isinstance(c.get("quote"), str)):
            raise ValueError('every claim needs a string "claim" and a string "quote"')
    return turn


class Agent:
    """One debater. Keeps its own conversation history between rounds."""

    def __init__(self, side, ticker, filing_text):
        self.side = side
        self.filing_text = filing_text
        self.system = SIDE_PROMPTS[side].format(ticker=ticker) + "\n\n" + OUTPUT_FORMAT
        self.messages = []

    def speak(self, opponent_argument=None):
        """Return this agent's turn as a dict: {"argument", "claims"}."""
        if not self.messages:
            # First turn: the agent sees the filing once; it stays in history.
            prompt = f"FILING EXCERPTS:\n{self.filing_text}\n\n"
            if opponent_argument:
                prompt += f"Your opponent argued:\n{opponent_argument}\n\n"
            prompt += "Give your opening argument."
        else:
            prompt = (
                f"Your opponent argued:\n{opponent_argument}\n\n"
                "Rebut their strongest points and strengthen your own case."
            )
        self.messages.append({"role": "user", "content": prompt})
        reply = ask_llm(self.system, self.messages)
        self.messages.append({"role": "assistant", "content": reply})

        try:
            return parse_turn(reply)
        except ValueError as error:  # json.JSONDecodeError is a ValueError too
            # One retry: tell the model what went wrong.
            self.messages.append(
                {"role": "user", "content": f"That reply was not usable ({str(error)[:200]}). "
                                            "Reply with ONLY the JSON object in the required format."}
            )
            reply = ask_llm(self.system, self.messages)
            self.messages.append({"role": "assistant", "content": reply})
            return parse_turn(reply)


def check_citations(turn, filing_text):
    """Add verified/score to every claim, using code (not the LLM)."""
    for claim in turn["claims"]:
        verified, score = verify_quote(claim["quote"], filing_text)
        claim["verified"] = verified
        claim["score"] = round(score, 1)


def citation_stats(rounds):
    stats = {}
    for side in ("bull", "bear"):
        claims = [c for r in rounds for c in r[side]["claims"]]
        ok = sum(1 for c in claims if c["verified"])
        stats[side] = {"verified": ok, "total": len(claims)}
    ok_all = stats["bull"]["verified"] + stats["bear"]["verified"]
    total_all = stats["bull"]["total"] + stats["bear"]["total"]
    stats["overall"] = {
        "verified": ok_all,
        "total": total_all,
        "accuracy": round(ok_all / total_all, 3) if total_all else 0.0,
    }
    return stats


def format_transcript(rounds, first="bull"):
    """Turn the debate into text for the judge.

    `first` is which side is listed first within each round. Swapping it
    lets us test whether the judge is biased by presentation order.

    Caveat: when `first` is not the side that actually spoke first, the
    judge reads the reply before the argument it answers, so a "position
    effect" measured this way also includes a scrambled conversation. The
    two debate setups (bull speaks first / bear speaks first) are the
    chronological comparison.
    """
    sides = ["bull", "bear"] if first == "bull" else ["bear", "bull"]
    lines = []
    for r in rounds:
        lines.append(f"ROUND {r['round']}")
        for side in sides:
            turn = r[side]
            lines.append(f"{side.upper()}: {turn['argument']}")
            for c in turn["claims"]:
                tag = "VERIFIED" if c["verified"] else "NOT VERIFIED"
                lines.append(f"  - claim: {c['claim']}")
                lines.append(f'    quote: "{c.get("quote", "")}" [{tag}, match {c["score"]}]')
        lines.append("")
    return "\n".join(lines)


def judge(rounds, first="bull", model=None):
    """Score a debate. `model` picks the judge (default: the debaters' model)."""
    transcript = format_transcript(rounds, first)
    messages = [{"role": "user", "content": f"DEBATE TRANSCRIPT:\n\n{transcript}\nJudge this debate."}]
    reply = ask_llm(JUDGE_SYSTEM, messages, model=model)
    try:
        return parse_json(reply)
    except ValueError:
        # One retry with the bad reply in history, like the debaters get.
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": "That was not valid JSON. Reply with ONLY the JSON object."})
        return parse_json(ask_llm(JUDGE_SYSTEM, messages, model=model))


def run_debate(ticker, num_rounds=2, bull_first=True):
    ticker = ticker.upper()
    sections = get_sections(ticker)
    filing_text = (
        "RISK FACTORS (Item 1A):\n" + sections["risk_factors"]
        + "\n\nMANAGEMENT'S DISCUSSION AND ANALYSIS (Item 7):\n" + sections["mdna"]
    )
    print(f"{ticker}: filing text is {len(filing_text.split()):,} words")

    before = dict(totals)
    agents = {side: Agent(side, ticker, filing_text) for side in ("bull", "bear")}
    order = ["bull", "bear"] if bull_first else ["bear", "bull"]
    last_argument = {"bull": None, "bear": None}
    rounds = []

    for n in range(1, num_rounds + 1):
        entry = {"round": n}
        for side in order:
            opponent = "bear" if side == "bull" else "bull"
            print(f"round {n}: {side} speaks")
            turn = agents[side].speak(last_argument[opponent])
            check_citations(turn, filing_text)
            entry[side] = turn
            last_argument[side] = turn["argument"]
        rounds.append(entry)

    print("judge deliberates")
    verdict = judge(rounds)

    return {
        "ticker": ticker,
        "filing": sections["filing"],
        "model": MODEL,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bull_first": bull_first,
        "rounds": rounds,
        "citations": citation_stats(rounds),
        "judge": verdict,
        "usage": {
            "calls": totals["calls"] - before["calls"],
            "input_tokens": totals["input_tokens"] - before["input_tokens"],
            "output_tokens": totals["output_tokens"] - before["output_tokens"],
            "cost_usd": round(totals["cost"] - before["cost"], 4),
        },
    }


def save_debate(debate, directory=DEBATE_DIR):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{debate['ticker']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(debate, f, indent=2, ensure_ascii=False)
    return path


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    debate = run_debate(ticker, rounds)
    path = save_debate(debate)

    c, j, u = debate["citations"], debate["judge"], debate["usage"]
    print(f"\nsaved {path}")
    print(f"winner: {j['winner']}  scores: {j['scores']}")
    print(f"citations verified: {c['overall']['verified']}/{c['overall']['total']} "
          f"(bull {c['bull']['verified']}/{c['bull']['total']}, "
          f"bear {c['bear']['verified']}/{c['bear']['total']})")
    print(f"cost: ${u['cost_usd']} over {u['calls']} calls")
