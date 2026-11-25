import json

import pytest

import phase_c
from debate import BALANCED_WORDS, build_filing_text


def words(n):
    return " ".join(f"w{i}" for i in range(n))


SECTIONS = {"risk_factors": words(10_000), "mdna": words(3_000)}


# --- input modes ---

def test_full_input_is_both_sections_untouched():
    text = build_filing_text(SECTIONS, "full")
    assert SECTIONS["risk_factors"] in text and SECTIONS["mdna"] in text
    assert build_filing_text(SECTIONS) == text  # "full" is the default


def test_balanced_input_takes_equal_chunks_of_each_section():
    text = build_filing_text(SECTIONS, "balanced")
    risk, mdna = text.split("MANAGEMENT'S DISCUSSION AND ANALYSIS (Item 7):\n")
    assert len(risk.split("RISK FACTORS (Item 1A):\n")[1].split()) == BALANCED_WORDS
    assert len(mdna.split()) == BALANCED_WORDS


def test_balanced_input_keeps_a_short_section_whole():
    short = {"risk_factors": words(10_000), "mdna": words(900)}
    assert len(build_filing_text(short, "balanced").split("(Item 7):\n")[1].split()) == 900


def test_unknown_input_mode_is_refused():
    with pytest.raises(ValueError, match="input_mode"):
        build_filing_text(SECTIONS, "mdna-only")


# --- the pre-set rule ---

def test_verdict_follows_the_preset_rule():
    v = phase_c.phase_c_verdict
    assert v(noise_gap=25, effect=40) == "too noisy to read"
    assert v(noise_gap=5, effect=-20) == "input-driven"
    assert v(noise_gap=5, effect=9.9) == "not input-driven"
    assert v(noise_gap=5, effect=15) == "inconclusive"
    # the effect must also beat twice the noise: 25 points is not enough against a 15-point noise gap
    assert v(noise_gap=15, effect=25) == "inconclusive"
    assert v(noise_gap=15, effect=30) == "input-driven"


def run(winner):
    return {"winner": winner, "margin": 0,
            "scores": {"bull": {"evidence": 5, "logic": 5, "responsiveness": 5},
                       "bear": {"evidence": 5, "logic": 5, "responsiveness": 5}}}


def test_compare_conditions_uses_the_average_of_both_full_runs_as_baseline():
    original = {"A": [run("bear")] * 3, "B": [run("bear")] * 3}
    rerun = {"A": [run("bear")] * 3, "B": [run("bull")] * 3}       # 100% and 50% -> noise 50
    balanced = {"A": [run("bull")] * 3, "B": [run("bull")] * 3}
    c = phase_c.compare_conditions(original, rerun, balanced)
    assert c["bear_share"] == {"original": 100.0, "rerun": 50.0, "balanced": 0.0}
    assert c["noise_gap"] == 50.0
    assert c["effect"] == -75.0
    assert c["verdict"] == "too noisy to read"


def test_compare_conditions_only_counts_companies_in_all_three():
    runs = {"A": [run("bear")] * 3}
    assert phase_c.compare_conditions(runs, runs, {}) is None
    c = phase_c.compare_conditions({"A": runs["A"], "B": runs["A"]}, runs, runs)
    assert c["debates"] == 1


def test_spearman_handles_ties_and_flat_input():
    assert phase_c.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert phase_c.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert phase_c.spearman([1, 1, 1], [1, 2, 3]) is None   # no spread in one list
    assert phase_c.spearman([1, 2], [1, 2]) is None          # too few points


# --- running a condition ---

def test_run_condition_writes_only_its_own_files_and_resumes(tmp_path, monkeypatch):
    """Regression-style: results go to the results file, debates to their own
    folder, nothing else is touched, and finished tickers are not redone."""
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run_debate(ticker, bull_first, input_mode):
        calls.append((ticker, input_mode))
        return {"ticker": ticker, "bull_first": bull_first, "input_mode": input_mode, "rounds": []}

    monkeypatch.setattr(phase_c, "run_debate", fake_run_debate)
    monkeypatch.setattr(phase_c, "judge_in_speaking_order", lambda debate: [run("bear")] * 3)

    results_file = tmp_path / "results" / "phase_c.json"
    out_dir = tmp_path / "debates" / "variants" / "phase-c-balanced"
    phase_c.run_condition("balanced", ["AAPL", "MSFT"], str(results_file), str(out_dir))

    assert calls == [("AAPL", "balanced"), ("MSFT", "balanced")]
    saved = json.loads(results_file.read_text(encoding="utf-8"))
    assert set(saved["balanced"]) == {"AAPL", "MSFT"}
    assert sorted(p.name for p in out_dir.iterdir()) == ["AAPL.json", "MSFT.json"]
    assert json.loads((out_dir / "AAPL.json").read_text(encoding="utf-8"))["input_mode"] == "balanced"

    phase_c.run_condition("balanced", ["AAPL", "MSFT"], str(results_file), str(out_dir))
    assert len(calls) == 2  # second call skipped both


def test_run_condition_reuses_a_saved_debate_when_only_judging_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "d"
    out_dir.mkdir()
    (out_dir / "AAPL.json").write_text(
        json.dumps({"ticker": "AAPL", "bull_first": True, "rounds": []}), encoding="utf-8")

    def must_not_run(*a, **k):
        raise AssertionError("regenerated a debate that was already saved")

    monkeypatch.setattr(phase_c, "run_debate", must_not_run)
    monkeypatch.setattr(phase_c, "judge_in_speaking_order", lambda debate: [run("bull")] * 3)
    results_file = tmp_path / "r.json"
    phase_c.run_condition("rerun", ["AAPL"], str(results_file), str(out_dir))
    assert "AAPL" in json.loads(results_file.read_text(encoding="utf-8"))["rerun"]
