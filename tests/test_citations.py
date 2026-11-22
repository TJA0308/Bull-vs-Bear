from citations import numbers_in, verify_quote

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


def test_changed_number_is_rejected_even_though_text_is_close():
    # "5%" became "15%": a tiny edit to the text, but a different fact.
    verified, score = verify_quote(
        "Revenue declined 15% in the quarter due to weaker demand", FILING
    )
    assert score >= 90  # the fuzzy score alone would have accepted it
    assert verified is False


def test_same_number_still_verifies_with_a_wording_slip():
    verified, _ = verify_quote(
        "Revenue declined 5% in a quarter due to weaker demand", FILING
    )
    assert verified is True


def test_numbers_in_ignores_trailing_commas():
    assert numbers_in("grew 1,200.5 or 5%, then 10,") == {"1,200.5", "5", "10"}


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
