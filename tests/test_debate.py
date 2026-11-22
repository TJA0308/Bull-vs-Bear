import json

import pytest

from debate import check_citations, parse_turn


def reply(**turn):
    return json.dumps(turn)


GOOD = {"argument": "A case.", "claims": [{"claim": "c", "quote": "some words from the filing here"}]}


def test_good_turn_parses():
    assert parse_turn(reply(**GOOD))["argument"] == "A case."


def test_null_quote_is_rejected_so_the_agent_can_retry():
    bad = {"argument": "x", "claims": [{"claim": "c", "quote": None}]}
    with pytest.raises(ValueError, match="quote"):
        parse_turn(reply(**bad))


def test_missing_claims_is_rejected():
    with pytest.raises(ValueError, match="claims"):
        parse_turn(reply(argument="x"))


def test_text_around_the_json_is_ignored():
    assert parse_turn("Here you go:\n" + reply(**GOOD) + "\nHope that helps")["claims"]


def test_check_citations_marks_each_claim():
    turn = {"claims": [{"claim": "c", "quote": "not in the filing at all, nothing alike"}]}
    check_citations(turn, "A short filing about something different entirely.")
    assert turn["claims"][0]["verified"] is False
    assert "score" in turn["claims"][0]


def test_unknown_judge_model_is_refused_before_any_api_call():
    import pytest
    from llm import ask_llm
    with pytest.raises(ValueError, match="No price known"):
        ask_llm("system", [{"role": "user", "content": "hi"}], model="claude-not-a-model")
