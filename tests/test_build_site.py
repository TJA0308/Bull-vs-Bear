"""The site's judge and noise sections are built from saved results (no API calls)."""
import build_site


def test_judges_summary_matches_phase_b():
    j = build_site.judges_summary()
    assert j["debates"] == 32
    assert j["verdict"] == "judge-driven"
    assert j["shiftPoints"] >= j["bigRule"]
    assert set(j["setups"]) == {"base", "bearFirst"}
    first, second = j["setups"]["base"]["first"], j["setups"]["base"]["second"]
    assert sum(first["counts"].values()) == first["judgments"] == 48
    assert second["counts"]["bear"] < first["counts"]["bear"]


def test_noise_summary_reports_unreadable_input_test():
    n = build_site.noise_summary()
    assert n["debates"] == 16
    assert n["verdict"] == "too noisy to read"
    assert n["noiseGap"] >= n["noiseLimit"]
    assert set(n["conditions"]) == {"original", "rerun", "balanced"}
    assert set(n["perCompany"]) and all(set(v) == {"original", "rerun"} for v in n["perCompany"].values())
