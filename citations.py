"""Check that a quote an agent used really appears in the filing.

This is plain Python, NOT an LLM, so the check can't be talked out of the truth.

Order of checks: too short -> exact substring -> fuzzy match.
Tests are in tests/test_citations.py.
"""
import re

from rapidfuzz import fuzz

MIN_WORDS = 5  # a 2-word "quote" matches almost anywhere and proves nothing


def normalize(text):
    """Make text comparable: straight quotes, lowercase, single spaces."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


def verify_quote(quote, filing_text, threshold=90):
    """Return (verified, score) where score is 0-100.

    verified is True when the quote matches somewhere in the filing with a
    score of at least `threshold`.
    """
    quote_n = normalize(quote)
    filing_n = normalize(filing_text)

    # 1. Too short to mean anything: a 2-word "quote" fuzzy-matches almost
    #    anywhere, so reject it before doing any matching.
    if len(quote_n.split()) < MIN_WORDS:
        return False, 0.0

    # 2. Fast path: an exact substring is instant and always right.
    if quote_n in filing_n:
        return True, 100.0

    # 3. Fuzzy path: slide the quote along the filing and score the
    #    best-matching window from 0 to 100.
    score = fuzz.partial_ratio(quote_n, filing_n)
    return score >= threshold, float(score)
