"""Check that a quote an agent used really appears in the filing.

This is plain Python, NOT an LLM, so the check can't be talked out of the truth.

STATUS: simple starter version (exact match only). Your job is to upgrade
verify_quote() with fuzzy matching so the failing tests in
tests/test_citations.py pass. Hints at the bottom.
"""
import re

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

    # Starter logic: exact substring or nothing.
    if quote_n and quote_n in filing_n:
        return True, 100.0
    return False, 0.0


# HINTS (try without them first):
# 1. Models misquote slightly (one word changed, a word dropped), so exact
#    matching rejects real quotes. Look at rapidfuzz.fuzz.partial_ratio: it
#    finds the best-matching window of the long text and scores it 0-100.
# 2. Keep the exact-match fast path: it is instant and always right.
# 3. Reject quotes shorter than MIN_WORDS words before matching.
# 4. partial_ratio on a whole filing is slower than a substring check, which
#    is one more reason to try the fast path first.
