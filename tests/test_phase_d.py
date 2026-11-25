"""Phase D: the pre-set rule and its helpers. No API calls."""
import json

import phase_c
import phase_d
from phase_d import (draw_score, edge_verdict, input_verdict, is_full, mean_ci,
                     t_crit, welch)


def run(winner, margin):
    return {"winner": winner, "margin": margin, "scores": {}}


def draw(margin, companies=16):
    return {f"T{i}": [run("bear" if margin < 0 else "bull", margin)] * 3 for i in range(companies)}


# --- helpers ---

def test_draw_score_is_the_mean_margin_over_all_judgments():
    d = {"A": [run("bear", -2), run("bear", -4), run("tie", 0)], "B": [run("bull", 3)] * 3}
    assert draw_score(d) == (-2 - 4 + 0 + 9) / 6


def test_only_complete_draws_count():
    assert is_full(draw(-1))
    assert not is_full(draw(-1, companies=15))
    assert not is_full({**draw(-1, companies=15), "X": []})


def test_t_values():
    assert t_crit(4) == 2.776
    assert t_crit(8) == 2.306


def test_mean_ci_needs_two_draws_and_matches_hand_calculation():
    assert mean_ci([-1.0]) == (-1.0, None)
    m, h = mean_ci([-1.0, -2.0, -3.0, -2.0, -2.0])
    assert m == -2.0
    assert abs(h - 2.776 * (0.5 ** 0.5) / 5 ** 0.5) < 1e-9  # sd of the five is sqrt(0.5)


def test_welch_is_zero_width_for_identical_constants():
    assert welch([-1.0] * 5, [-1.0] * 5) == (0.0, 0.0)


# --- question 1: how big is the bear's edge ---

def test_edge_verdicts():
    assert edge_verdict([-1.9, -2.0, -1.8, -2.1, -2.0]) == "bear edge confirmed"
    assert edge_verdict([-1.0, 1.0, -0.5, 0.8, 0.2]) == "no clear edge"
    assert edge_verdict([2.0, 1.9, 2.1, 2.0, 1.8]) == "bull edge"
    assert edge_verdict([-2.0]) == "not enough draws"


# --- question 2: does balancing the input change the margin ---

FULL = [-2.0, -1.9, -2.1, -2.0, -2.0]


def test_a_clear_shift_of_at_least_one_point_is_input_driven():
    assert input_verdict(FULL, [-0.5, -0.4, -0.6, -0.5, -0.5]) == "input-driven"
    assert input_verdict(FULL, [-3.5, -3.4, -3.6, -3.5, -3.5]) == "input-driven"  # either direction


def test_tight_draws_with_no_shift_are_not_input_driven():
    assert input_verdict(FULL, [-2.0, -1.9, -2.1, -2.0, -2.0]) == "not input-driven"


def test_wide_spread_is_too_noisy_even_with_a_big_gap():
    noisy = [-4.0, 0.0, -3.0, 1.0, -1.0]
    assert input_verdict(FULL, noisy) == "too noisy to read"


def test_a_small_but_precisely_measured_shift_is_still_not_input_driven():
    # shift 0.8 with a very tight interval: the whole interval is inside (-1, +1)
    assert input_verdict(FULL, [-1.2, -1.1, -1.3, -1.2, -1.2]) == "not input-driven"


def test_an_interval_that_straddles_the_line_is_inconclusive():
    # shift 0.8, interval about (0.35, 1.25): under 1.0 so not "input-driven",
    # but it reaches past 1.0 so it cannot be called "not input-driven" either
    assert input_verdict(FULL, [-1.6, -0.9, -1.2, -0.8, -1.5]) == "inconclusive"


def test_too_few_draws_cannot_be_judged():
    assert input_verdict(FULL, [-1.0]) == "not enough draws"


# --- loading and running ---

def test_load_draws_skips_incomplete_draws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "chronological.json").write_text(json.dumps({"base": draw(-2)}), encoding="utf-8")
    (tmp_path / "results" / "phase_c.json").write_text(
        json.dumps({"rerun": draw(-1), "balanced": draw(-1, companies=5)}), encoding="utf-8")
    (tmp_path / "results" / "phase_d.json").write_text(
        json.dumps({"full-3": draw(-2), "balanced-2": draw(-1)}), encoding="utf-8")
    draws = phase_d.load_draws()
    assert len(draws["full"]) == 3          # original, rerun, full-3
    assert len(draws["balanced"]) == 1      # the 5-company Phase C draw is dropped


def test_run_draw_uses_its_own_mode_files_and_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    modes = []

    def fake_run_debate(ticker, bull_first, input_mode):
        modes.append(input_mode)
        return {"ticker": ticker, "bull_first": True, "input_mode": input_mode, "rounds": []}

    monkeypatch.setattr(phase_c, "run_debate", fake_run_debate)
    monkeypatch.setattr(phase_c, "judge_in_speaking_order", lambda debate: [run("bear", -2)] * 3)
    monkeypatch.setattr(phase_c, "TICKERS", ["AAPL"])
    phase_d.run_draw("balanced-2")
    assert modes == ["balanced"]
    saved = json.loads((tmp_path / "results" / "phase_d.json").read_text(encoding="utf-8"))
    assert list(saved) == ["balanced-2"]
    assert (tmp_path / "debates" / "variants" / "phase-d-balanced-2" / "AAPL.json").exists()
    assert not (tmp_path / "results" / "phase_c.json").exists()
