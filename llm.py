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
# Dollars per 1M tokens for prompts up to 100K tokens (check the pricing page,
# these change). Longer prompts cost more, so keep filings under that.
PRICE_IN = 0.10
PRICE_OUT = 0.50

# Running totals for the whole process, so a debate can report its cost.
totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}


def ask_llm(system, messages, max_tokens=4000):
    """Send one request. Returns the reply text.

    messages is the conversation so far: a list of
    {"role": "user" | "assistant", "content": "..."} dicts.
    Claude has no memory between calls, so we resend it every time.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        output_config={"effort": "low"},  # less thinking = cheaper and faster
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError("Reply was cut off at max_tokens; raise the limit")

    usage = response.usage
    cost = (usage.input_tokens * PRICE_IN + usage.output_tokens * PRICE_OUT) / 1_000_000
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
