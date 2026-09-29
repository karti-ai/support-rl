"""The Zoomberg example must reproduce the published numbers exactly.

Karti-Small-Support-9B v1 (model card) and the frozen baselines were scored with the
reference scorer "fst-scorer-v4". Re-scoring the saved outputs in examples/zoomberg/results/
with this package and examples/zoomberg/supportrl.yaml must give the same numbers. A change
to the scorer that moves any of them is a scoring change and needs a new version.
"""

from __future__ import annotations

import hashlib

import pytest

from helpers import ZOOMBERG
from supportrl.data import load_split
from supportrl.pack import Pack
from supportrl.probes import report
from supportrl.report import load_run, paired_bootstrap
from supportrl.runs import load_outputs, score_outputs, summarise

ADV = ["H1_disclosure_before_verification", "H4_advice_given"]
R = ZOOMBERG / "results"

# split, run, composite, H1/H4 advisory, no hard gate, hard-failed, hard hits H1..H5
PUBLISHED = [
    ("test", "qwen3.5-4b-base", 0.502, 0.552, 0.562, 3, (2, 1, 0, 0, 0)),
    ("test", "qwen3.5-9b-base", 0.531, 0.569, 0.638, 6, (2, 2, 1, 0, 1)),
    ("test", "support-9b-v1", 0.706, 0.738, 0.738, 1, (1, 0, 0, 0, 0)),
    ("test", "support-9b-v2", 0.606, 0.637, 0.688, 4, (1, 1, 0, 0, 2)),
    ("test", "support-9b-v3", 0.695, 0.726, 0.726, 1, (1, 0, 0, 0, 0)),
    ("dev", "qwen3.5-4b-base", 0.507, None, None, None, None),
    ("dev", "qwen3.5-9b-base", 0.509, None, None, None, None),
    ("dev", "support-9b-v1", 0.747, None, None, None, None),
    ("dev_val", "v1-candidate-step07", 0.644, None, None, None, None),
    ("dev_val", "v1-candidate-step14", 0.786, None, None, None, None),
    ("dev_val", "v1-candidate-step21", 0.514, None, None, None, None),
]


def _summary(pack, split, run, advisory=None):
    rows, _ = load_outputs(R / split / run)
    eps = {e["id"]: e for e in load_split(pack, split, allow_locked=True)}
    return summarise(pack, score_outputs(pack, eps, rows), advisory)


@pytest.mark.parametrize("split,run,comp,adv,nogate,hf,hits", PUBLISHED)
def test_published_numbers(zpack, split, run, comp, adv, nogate, hf, hits):
    s = _summary(zpack, split, run, ADV)
    assert round(s["composite"], 3) == comp
    if adv is not None:
        assert round(s["composite_advisory"], 3) == adv
        assert round(s["composite_no_hard_gate"], 3) == nogate
        assert s["episodes_hard_failed"] == hf
        assert tuple(s["hard_violations"].values()) == hits
        assert s["format_invalid"] == 0


def test_v1_components_and_rates(zpack):
    s = _summary(zpack, "test", "support-9b-v1")
    got = {k: round(v, 3) for k, v in s["components"].items()}
    assert got == {"action_type": 0.679, "destination": 0.623, "priority": 0.660, "flags": 0.836,
                   "policy_citation": 0.737, "must_ask": 0.849}  # fmt: skip
    assert round(s["over_escalation_rate"], 3) == 0.0 and round(s["under_route_rate"], 3) == 0.094
    assert s["action_type_correct"] == {"ask_clarifying": "0/2", "ask_verification": "2/7", "escalate": "4/6",
                                        "resolve": "17/19", "route": "13/19"}  # fmt: skip


def test_dev_subsets(zpack):
    rows, _ = load_outputs(R / "dev" / "support-9b-v1")
    from supportrl.runs import summarise_run

    eps = {e["id"]: e for e in load_split(zpack, "dev")}
    s = summarise_run(zpack, "dev", score_outputs(zpack, eps, rows))
    assert round(s["dev_val"]["composite"], 3) == 0.775 and round(s["dev_holdout"]["composite"], 3) == 0.719


def test_v1_vs_base_bootstrap(zpack):
    base = load_run(zpack, R / "test" / "qwen3.5-9b-base")
    v1 = load_run(zpack, R / "test" / "support-9b-v1")
    b = paired_bootstrap(base["rewards"], v1["rewards"])
    assert round(b["delta"], 3) == 0.175 and (b["better"], b["worse"], b["same"]) == (19, 3, 10)
    assert 0.03 < b["lo"] < 0.08 and 0.27 < b["hi"] < 0.33  # published: [+0.055, +0.298]


def test_v5_variant_rescoring(zpack):
    """v5 (the ask gate) re-scores the same outputs: 4B 0.481, 9B 0.526, v1 0.666, v2 0.597."""
    v5 = Pack(ZOOMBERG, "v5")
    runs = ("qwen3.5-4b-base", "qwen3.5-9b-base", "support-9b-v1", "support-9b-v2", "support-9b-v3")
    got = [round(_summary(v5, "test", r)["composite"], 3) for r in runs]
    assert got == [0.481, 0.526, 0.666, 0.597, 0.664]


def test_v2_negative_result(zpack):
    """v2 recovered the verification asks but lost routing, and failed its ship rule (v4 >= 0.69)."""
    s = _summary(zpack, "test", "support-9b-v2")
    assert s["action_type_correct"]["ask_verification"] == "5/7"
    assert s["action_type_correct"]["resolve"] == "9/19"
    assert round(s["composite"], 3) < 0.69
    v5 = Pack(ZOOMBERG, "v5")
    assert round(_summary(v5, "dev", "support-9b-v2")["composite"], 3) == 0.589
    cands = {
        k: round(_summary(v5, "dev_val", f"v2-candidate-step{k:02d}")["composite"], 3) for k in (7, 14, 21)
    }
    assert cands == {7: 0.664, 14: 0.475, 21: 0.594}


def test_probe_recall_matches_published(zpack):
    r = {s["file"]: s for s in report(zpack)["sets"]}
    assert round(r["h1.holdout.jsonl"]["recall"], 2) == 0.88
    assert round(r["h4.holdout.jsonl"]["recall"], 2) == 0.62
    assert r["h5.holdout.jsonl"]["recall"] == 1.0
    # holdout-v2 for H4 was used to fix the detector after its first measurement: quote 0.50
    assert r["h4.holdout-v2.jsonl"]["seen"] and r["h4.holdout-v2.jsonl"]["quoted_recall"] == 0.50
    assert not r["h5.holdout-v2.jsonl"]["seen"]
    assert all(s["precision"] in (1.0, None) for s in r.values())
    assert report(zpack)["advisory"] == ADV


def test_system_prompt_is_the_one_v1_was_trained_with(zpack):
    h = hashlib.sha256(zpack.system_prompt().encode()).hexdigest()
    assert h == "9e16d510cc0d741b148d50471ec20379707b5b64761b3a7f50bf859ee5b85331"
    assert hashlib.sha256(zpack.policy_text.encode()).hexdigest().startswith("081b01aeed39")


def test_v3_flat_vs_v1_and_asks_not_recovered(zpack):
    """v3 (v1 continued under v5): composite 0.695, asks still 2/7, v3 - v1 = -0.011 [-0.060, +0.046]."""
    s = _summary(zpack, "test", "support-9b-v3")
    assert s["action_type_correct"]["ask_verification"] == "2/7"
    assert s["action_type_correct"]["resolve"] == "13/19" and s["action_type_correct"]["route"] == "13/19"
    b = paired_bootstrap(load_run(zpack, R / "test" / "support-9b-v1")["rewards"],
                         load_run(zpack, R / "test" / "support-9b-v3")["rewards"])  # fmt: skip
    assert round(b["delta"], 3) == -0.011 and (b["better"], b["worse"], b["same"]) == (4, 9, 19)
    assert round(b["lo"], 3) == -0.060 and round(b["hi"], 3) == 0.046
    v5 = Pack(ZOOMBERG, "v5")
    rows, _ = load_outputs(R / "dev" / "support-9b-v3")
    from supportrl.runs import summarise_run

    eps = {e["id"]: e for e in load_split(v5, "dev")}
    d = summarise_run(v5, "dev", score_outputs(v5, eps, rows))
    assert round(d["all"]["composite"], 3) == 0.704
    assert (
        round(d["dev_val_v2"]["composite"], 3) == 0.692
        and round(d["dev_holdout_v2"]["composite"], 3) == 0.717
    )


def test_v3_multipass_ask_guard_selection():
    """The predeclared v3 rule: 3 T=0 passes per candidate on dev_val_v2, ask guard = the 9B base.
    Every candidate asks 0/6 and fails the guard; the fallback picks step 24 (mean 0.692)."""
    from supportrl_train.select import select_runs

    v5 = Pack(ZOOMBERG, "v5")
    passes = lambda n: [str(R / "dev_val_v2" / f"{n}-p{k}") for k in (1, 2, 3)]  # noqa: E731
    cands = {f"step{s}": passes(f"v3-candidate-step{s}") for s in (16, 20, 24, 28)}
    res = select_runs(v5, cands, "dev_val_v2", passes("qwen3.5-9b-base"))
    assert res["reference"]["ask_pooled"] == "2/6" and round(res["reference"]["mean_composite"], 3) == 0.436
    means = {k: round(v["mean_composite"], 3) for k, v in res["candidates"].items()}
    assert means == {"step16": 0.684, "step20": 0.675, "step24": 0.692, "step28": 0.571}
    assert all(c["ask_pooled"] == "0/6" and c["passes_guard"] is False for c in res["candidates"].values())
    assert res["guard_all_failed"] and res["selected"] == "step24"
    assert round(res["candidates"]["step28"]["spread"], 3) == 0.019
