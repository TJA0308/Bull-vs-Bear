"""Check that a quote an agent used really appears in the filing.

This is plain Python, NOT an LLM, so the check can't be talked out of the truth.

Order of checks: too short -> exact substring -> fuzzy match -> numbers agree.
Tests are in tests/test_citations.py.
"""
import re
from functools import lru_cache

from rapidfuzz import fuzz

MIN_WORDS = 5  # a 2-word "quote" matches almost anywhere and proves nothing


def normalize(text):
    """Make text comparable: straight quotes, lowercase, single spaces."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
WINDOW_PAD = 10  # characters of slack around the matched window


@lru_cache(maxsize=16)
def _normalize_filing(filing_text):
    """A filing is normalized once, not once per quote."""
    return normalize(filing_text)


def numbers_in(text):
    """The numbers in a text, e.g. '5%' -> '5', '$1,200.5' -> '1,200.5'."""
    return {m.rstrip(",") for m in NUMBER.findall(text)}


def verify_quote(quote, filing_text, threshold=90):
    """Return (verified, score) where score is 0-100.

    verified is True when the quote matches somewhere in the filing with a
    score of at least `threshold` AND every number in the quote also appears
    in the part of the filing it matched. A fuzzy score cannot see that "5%"
    became "15%": one digit is a tiny edit on a long quote.
    """
    quote_n = normalize(quote)
    filing_n = _normalize_filing(filing_text)

    # 1. Too short to mean anything: a 2-word "quote" fuzzy-matches almost
    #    anywhere, so reject it before doing any matching.
    if len(quote_n.split()) < MIN_WORDS:
        return False, 0.0

    # 2. Fast path: an exact substring is instant and always right.
    if quote_n in filing_n:
        return True, 100.0

    # 3. Fuzzy path: slide the quote along the filing and score the
    #    best-matching window from 0 to 100.
    match = fuzz.partial_ratio_alignment(quote_n, filing_n)
    score = float(match.score)
    if score < threshold:
        return False, score

    # 4. Numbers must survive: a quote that changes a figure is not verified.
    window = filing_n[max(0, match.dest_start - WINDOW_PAD):match.dest_end + WINDOW_PAD]
    return numbers_in(quote_n) <= numbers_in(window), score
