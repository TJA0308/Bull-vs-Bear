import pytest

from fetch import (ITEM_1A_END, ITEM_1A_START, checked_section, extract_section)

BODY = "Our business faces many risks. " * 200  # about 1,000 words


def filing(section_text):
    """A tiny filing: a table of contents that names the items, then the real ones."""
    return (
        "Table of contents Item 1A. Risk Factors 5 Item 1B. Unresolved Staff Comments 20 "
        "Part I see Item 1A. Risk Factors for more. "
        f"Item 1A. Risk Factors {section_text} Item 1B. Unresolved Staff Comments None."
    )


def test_picks_the_real_section_not_the_table_of_contents():
    section = extract_section(filing(BODY), ITEM_1A_START, ITEM_1A_END)
    assert "many risks" in section
    assert len(section.split()) > 900


def test_heading_with_an_em_dash_is_found():
    text = f"Item 1A—Risk Factors {BODY} Item 1B—Unresolved Staff Comments"
    assert "many risks" in extract_section(text, ITEM_1A_START, ITEM_1A_END)


def test_heading_split_across_tags_is_found():
    text = f"Item 1A. RIS K FACTORS {BODY} Item 1B. Unresolved Staff Comments"
    assert "many risks" in extract_section(text, ITEM_1A_START, ITEM_1A_END)


def test_missing_section_raises():
    with pytest.raises(ValueError, match="not found"):
        extract_section("nothing relevant here", ITEM_1A_START, ITEM_1A_END)


def test_too_short_section_fails_loudly():
    with pytest.raises(ValueError, match="only"):
        checked_section("Risk Factors", filing("incorporated by reference"),
                        ITEM_1A_START, ITEM_1A_END)
