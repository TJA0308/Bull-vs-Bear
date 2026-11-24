"""The ONE place that talks to Claude.

Everything else (debate, judge, ...) calls ask_llm(). To change the model,
add logging, or switch providers, this is the only file to touch.
"""
import json

import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()

MODEL = "claude-haiku-5-5"
# Dollars per 1M tokens (input, output). Check the pricing page, these change.
# Haiku's price is for prompts up to 100K tokens; longer prompts cost more, so
# keep filings under that.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}

# Running totals for the whole process, so a debate can report its cost.
totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}


def ask_llm(system, messages, max_tokens=4000, model=None):
    """Send one request. Returns the reply text.

    model defaults to MODEL; pass another (it must be in PRICES) to use a
    different one for a single call, e.g. a different judge.

    messages is the conversation so far: a list of
    {"role": "user" | "assistant", "content": "..."} dicts.
    Claude has no memory between calls, so we resend it every time.
    """
    model = model or MODEL
    if model not in PRICES:
        raise ValueError(f"No price known for {model!r}; add it to PRICES in llm.py")
    price_in, price_out = PRICES[model]
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        output_config={"effort": "low"},  # less thinking = cheaper and faster
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError("Reply was cut off at max_tokens; raise the limit")

    usage = response.usage
    cost = (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000
    totals["calls"] += 1
    totals["input_tokens"] += usage.input_tokens
    totals["output_tokens"] += usage.output_tokens
    totals["cost"] += cost
    print(f"  [llm] in={usage.input_tokens:,} out={usage.output_tokens:,} cost=${cost:.4f}")

    # content is a list of blocks; thinking blocks may come first, so keep text only
    return "".join(block.text for block in response.content if block.type == "text")


def parse_json(text):
    """Pull the first JSON object out of a model reply.

    The model may add words before or after the JSON, so we start at the
    first "{" and let raw_decode read exactly one object, ignoring the rest.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in reply: {text[:300]!r}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        raise ValueError(f"Bad JSON ({e}) in reply: {text[:300]!r}") from e
    return obj
