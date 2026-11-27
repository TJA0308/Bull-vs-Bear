"""Claim-support check: sampling, label sheet, scoring and the pre-set rule. No API calls."""
import csv
import csv
import json

import pytest

import claim_support as cs


def fake_pairs():
    pairs = []
    for t in ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]:
        for k in range(8):
            pairs.append({"ticker": t, "round": 1 + k % 2, "side": "bull" if k % 2 else "bear", "index": k,
                          "claim": f"{t} claim {k}", "quote": f"{t} quote number {k} has five words"})
    return pairs


# --- loading ---

def test_load_pairs_keeps_only_verified_claims(tmp_path):
    debate = {"ticker": "AAA", "rounds": [{"round": 1,
              "bull": {"claims": [{"claim": "c1", "quote": "q1", "verified": True},
                                  {"claim": "c2", "quote": "q2", "verified": False}]},
              "bear": {"claims": [{"claim": "c3", "quote": "q3", "verified": True}]}}]}
    (tmp_path / "AAA.json").write_text(json.dumps(debate), encoding="utf-8")
    pairs = cs.load_pairs(str(tmp_path))
    assert [p["claim"] for p in pairs] == ["c1", "c3"]
    assert pairs[1]["side"] == "bear" and pairs[1]["index"] == 0


# --- sampling ---

def test_sample_has_the_planned_mix_and_unique_ids():
    items = cs.build_sample(fake_pairs(), n_real=10, n_mismatched=4)
    assert len(items) == 14
    kinds = [i["built_as"] for i in items]
    assert kinds.count("real") == 10
    assert kinds.count("mismatch_other_company") == 2 and kinds.count("mismatch_same_company") == 2
    assert [i["id"] for i in items] == [f"P{n:02d}" for n in range(1, 15)]


def test_at_most_two_real_pairs_per_company():
    items = cs.build_sample(fake_pairs(), n_real=12, n_mismatched=0)
    counts = {}
    for i in items:
        counts[i["ticker"]] = counts.get(i["ticker"], 0) + 1
    assert max(counts.values()) == 2


def test_mismatches_pair_a_claim_with_a_quote_from_elsewhere():
    items = cs.build_sample(fake_pairs(), n_real=10, n_mismatched=6)
    for i in items:
        src = i["source"]
        if i["built_as"] == "real":
            assert src["claim_from"] == src["quote_from"]
        else:
            assert src["claim_from"] != src["quote_from"]
            same = src["claim_from"].split()[0] == src["quote_from"].split()[0]
            assert same == (i["built_as"] == "mismatch_same_company")


def test_no_claim_or_quote_is_used_twice():
    items = cs.build_sample(fake_pairs(), n_real=12, n_mismatched=8)
    assert len({i["claim"] for i in items}) == len(items)
    assert len({i["quote"] for i in items}) == len(items)


def test_sampling_is_reproducible():
    assert cs.build_sample(fake_pairs()) == cs.build_sample(fake_pairs())


# --- label sheet ---

def test_label_sheet_round_trip(tmp_path):
    items = cs.build_sample(fake_pairs(), n_real=4, n_mismatched=2)
    path = str(tmp_path / "labels.csv")
    cs.write_label_sheet(items, path)
    assert "built_as" not in open(path, encoding="utf-8-sig").read()   # the labeller must not see how a pair was built
    with pytest.raises(ValueError) as e:
        cs.read_labels(path)                                           # blank labels are refused
    assert "P01" in str(e.value)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    for n, row in enumerate(rows[1:]):
        row[3] = "Yes " if n % 2 else "no"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    assert set(cs.read_labels(path).values()) == {"yes", "no"}         # case and spaces are forgiven


def test_unknown_label_is_refused(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text("id,claim,quote,label\nP01,c,q,maybe\n", encoding="utf-8")
    with pytest.raises(ValueError):
        cs.read_labels(str(path))


# --- the model call ---

def test_check_support_retries_once_on_bad_json(monkeypatch):
    replies = iter(["I think it is fine", '{"verdict": "Partly", "reason": "no number"}'])
    monkeypatch.setattr(cs, "ask_llm", lambda *a, **k: next(replies))
    assert cs.check_support("c", "q") == {"verdict": "partly", "reason": "no number"}


def test_check_support_gives_up_after_two_bad_replies(monkeypatch):
    monkeypatch.setattr(cs, "ask_llm", lambda *a, **k: '{"verdict": "maybe"}')
    with pytest.raises(ValueError):
        cs.check_support("c", "q")


# --- scoring and the pre-set rule ---

def labels(*xs):
    return {f"P{n}": x for n, x in enumerate(xs, 1)}


def test_score_matches_a_hand_count():
    human = labels("yes", "yes", "partly", "no", "no", "no")
    model = labels("yes", "partly", "partly", "no", "yes", "no")
    s = cs.score(human, model)
    assert s["n"] == 6
    assert s["agree_3"] == 4 / 6
    assert s["agree_binary"] == 5 / 6        # only P5 (human no, model yes) differs on supported-vs-not
    assert s["miss_rate"] == 1 / 3           # one of three human "no" pairs let through
    assert s["baseline_binary"] == 0.5       # "always yes" is right on the 3 supported pairs
    assert s["confusion"]["no"]["yes"] == 1


def test_score_only_counts_ids_present_in_both():
    s = cs.score(labels("yes", "no", "no"), {"P1": "yes", "P2": "no"})
    assert s["n"] == 2


def test_keep_when_all_three_conditions_hold():
    human = labels(*["yes"] * 8 + ["partly"] * 2 + ["no"] * 10)
    model = labels(*["yes"] * 8 + ["partly"] * 2 + ["no"] * 10)
    assert cs.decide(cs.score(human, model)) == "keep"


def test_drop_when_it_lets_too_many_unsupported_pairs_through():
    human = labels(*["yes"] * 10 + ["no"] * 10)
    model = labels(*["yes"] * 10 + ["partly"] * 3 + ["no"] * 7)   # misses 30%; A and B are 85%
    s = cs.score(human, model)
    assert s["agree_3"] >= cs.MIN_AGREE_3 and s["agree_binary"] >= 0.85
    assert cs.decide(s) == "drop"


def test_drop_when_it_confuses_yes_and_partly_too_often():
    human = labels(*["yes"] * 10 + ["partly"] * 10 + ["no"] * 10)
    model = labels(*["yes"] * 10 + ["yes"] * 10 + ["no"] * 10)
    s = cs.score(human, model)
    assert s["agree_binary"] == 1.0 and s["miss_rate"] == 0.0
    assert cs.decide(s) == "drop"            # A is 67%, under 70%


def test_no_human_no_pairs_means_not_enough_data():
    assert cs.decide(cs.score(labels("yes", "yes"), labels("yes", "no"))) == "not enough data"
    assert cs.decide(None) == "not enough data"


# --- the labelling page's saving ---

def sheet(tmp_path):
    path = str(tmp_path / "labels.csv")
    cs.write_label_sheet(cs.build_sample(fake_pairs(), n_real=4, n_mismatched=2), path)
    return path


def test_set_label_changes_only_its_row_and_can_clear(tmp_path):
    path = sheet(tmp_path)
    before = cs.read_rows(path)
    cs.set_label(path, "P02", " Partly ")
    after = cs.read_rows(path)
    assert [r["label"] for r in after] == ["", "partly", "", "", "", ""]
    assert [(r["claim"], r["quote"]) for r in after] == [(r["claim"], r["quote"]) for r in before]
    cs.set_label(path, "P02", "")
    assert all(r["label"] == "" for r in cs.read_rows(path))


def test_set_label_refuses_bad_input(tmp_path):
    path = sheet(tmp_path)
    with pytest.raises(ValueError):
        cs.set_label(path, "P01", "maybe")
    with pytest.raises(ValueError):
        cs.set_label(path, "P99", "yes")
    assert all(r["label"] == "" for r in cs.read_rows(path))


def test_labelling_server_serves_pairs_and_saves_labels(tmp_path):
    import threading
    import urllib.error
    import urllib.request
    from http.server import HTTPServer
    path = sheet(tmp_path)
    server = HTTPServer(("127.0.0.1", 0), cs.make_handler(path))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        pairs = json.load(urllib.request.urlopen(base + "/api/pairs"))
        assert len(pairs) == 6 and set(pairs[0]) == {"id", "claim", "quote", "label"}   # no key leaks out
        req = lambda body: urllib.request.Request(base + "/api/label", json.dumps(body).encode(),
                                                  {"Content-Type": "application/json"})
        assert urllib.request.urlopen(req({"id": "P03", "label": "no"})).status == 200
        assert cs.read_labels.__name__ and cs.read_rows(path)[2]["label"] == "no"
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req({"id": "P03", "label": "maybe"}))
        assert e.value.code == 400
        assert b"Does the quote support the claim" in urllib.request.urlopen(base + "/").read()
    finally:
        server.shutdown()
        server.server_close()
