from citations import verify_quote

FILING = (
    "The Company’s products face intense competition. "
    "Our supply chain depends on a single region, which could disrupt "
    "operations. Revenue declined 5% in the quarter due to weaker demand."
)


def test_exact_quote_is_verified():
    verified, score = verify_quote(
        "Our supply chain depends on a single region, which could disrupt operations",
        FILING,
    )
    assert verified is True
    assert score == 100


def test_case_and_whitespace_differences_are_ignored():
    verified, _ = verify_quote(
        "our   SUPPLY chain depends on\na single region, which could disrupt operations",
        FILING,
    )
    assert verified is True


def test_straight_apostrophe_matches_curly_one():
    verified, _ = verify_quote("The Company's products face intense competition", FILING)
    assert verified is True


def test_one_changed_word_still_verifies():
    # The model swapped "region" for "area". A human would call this the same quote.
    verified, score = verify_quote(
        "Our supply chain depends on a single area, which could disrupt operations",
        FILING,
    )
    assert verified is True
    assert score >= 90


def test_fabricated_quote_is_rejected():
    verified, score = verify_quote(
        "Management expects record profits and sees no material risks ahead",
        FILING,
    )
    assert verified is False
    assert score < 90


def test_too_short_quote_is_rejected():
    # "Revenue declined" is really in the filing, but 2 words prove nothing.
    verified, _ = verify_quote("Revenue declined", FILING)
    assert verified is False


def test_empty_quote_is_rejected():
    verified, score = verify_quote("", FILING)
    assert verified is False
    assert score == 0
