from bias import analyze, majority, pair_verdict


def run(winner, margin=0):
    return {"winner": winner, "margin": margin, "scores": {}}


def debate(bull_first, bear_first):
    """Build one debate's results from two lists of (winner, margin)."""
    return {"bull_first": [run(*x) for x in bull_first],
            "bear_first": [run(*x) for x in bear_first]}


def test_majority_needs_more_than_half():
    assert majority(["bear", "bear", "bull"]) == "bear"
    assert majority(["tie", "tie", "tie"]) == "tie"


def test_three_way_disagreement_is_a_split_not_a_tie():
    assert majority(["bull", "bear", "tie"]) == "split"


def test_pair_verdict_adds_margins():
    assert pair_verdict(run("bull", 5), run("bear", -2)) == "bull"
    assert pair_verdict(run("bull", 3), run("bear", -3)) == "tie"


def test_all_ties_does_not_crash():
    ties = [("tie", 0)] * 3
    summary = analyze({"AAPL": debate(ties, ties)})
    assert summary["bull_wins"] is None
    assert summary["first_listed_wins"] is None
    assert summary["ties"] == 6


def test_a_real_order_flip_is_counted():
    d = debate([("bear", -4)] * 3, [("bull", 4)] * 3)
    assert analyze({"AAPL": d})["order_flip_rate"] == 1.0


def test_split_majority_is_not_counted_as_a_flip():
    d = debate([("bear", -4)] * 3, [("bull", 4), ("bear", -4), ("tie", 0)])
    s = analyze({"AAPL": d})
    assert s["order_flip_rate"] == 0.0
    assert s["unclear_majority_debates"] == 1


def test_position_bonus_is_half_the_margin_gap():
    # Bull is ahead by 6 when listed first and behind by 2 when listed second.
    d = debate([("bull", 6)] * 3, [("bear", -2)] * 3)
    assert analyze({"AAPL": d})["first_position_bonus_points"] == 4.0


def test_chronological_summary_counts_and_instability():
    from bias import analyze_chronological
    runs = {
        "AAPL": [run("bear", -3), run("bear", -5), run("bear", -1)],
        "MSFT": [run("bull", 2), run("tie", 0), run("bear", -2)],
    }
    s = analyze_chronological(runs)
    assert s["counts"] == {"bull": 1, "tie": 1, "bear": 4}
    assert s["same_order_instability"] == 0.5
    assert s["mean_margin"] == -1.5


def test_chronological_summary_of_nothing_is_none():
    from bias import analyze_chronological
    assert analyze_chronological({}) is None
