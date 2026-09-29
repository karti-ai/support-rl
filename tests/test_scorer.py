"""The scorer on the Zoomberg example.

Gold (each target's action fields, with a neutral reply that asks for every must_ask key)
must score exactly 1.0 on every decision of every split. Changing exactly one component must
cost exactly that component's weight times the fraction lost, no more and no less, unless
the change also trips a hard criterion, in which case the decision must score exactly 0.
"""

from __future__ import annotations

import json

import pytest

from helpers import ASK_SENTENCES, NEUTRAL, all_decisions, gold_obj
from supportrl.data import load_split
from supportrl.detectors.must_ask import asked
from supportrl.pack import Pack
from supportrl.scorer import Scorer

EXACT = {"H2_fraud_not_immediate", "H3_regulatory_not_escalated"}


def score(sc, obj, target, customer, ctx=None, **kw):
    return sc.score_decision(
        "d", target, json.dumps(obj), customer, ctx or {"account_masked": "****0000"}, **kw
    )


def test_gold_is_one_everywhere(zpack, zscorer):
    n = 0
    for split in ("train", "dev", "test"):
        for ep, dp, t, customer in all_decisions(zpack, split):
            s = score(zscorer, gold_obj(t), t, customer, ep["context"])
            n += 1
            assert s.format_valid, (ep["id"], dp, s.format_error)
            assert s.hard_zeroing == [], (ep["id"], dp, s.hard)
            assert s.score == pytest.approx(1.0), (ep["id"], dp, s.components)
    assert n == 156


def test_gold_episode_reward_is_one(zpack, zscorer):
    for split in ("train", "dev"):
        for ep in load_split(zpack, split):
            resp = [json.dumps(gold_obj(ep["decisions"][d])) for d in ep["decisions"]]
            assert zscorer.score_episode(ep, resp).reward == pytest.approx(1.0), ep["id"]


# ---------------------------------------------------------------------------- corruptions
def _check(zpack, sc, mutate, expected_loss, applies=lambda t: True, hard_ok=None):
    checked = 0
    for split in ("train", "dev"):
        for ep, dp, t, customer in all_decisions(zpack, split):
            if not applies(t):
                continue
            obj = gold_obj(t)
            mutate(obj, t)
            s = score(sc, obj, t, customer, ep["context"])
            assert s.format_valid, (ep["id"], dp, s.format_error)
            checked += 1
            if s.hard_zeroing:
                assert hard_ok is not None and hard_ok(t, s), (ep["id"], dp, "unexpected hard hit", s.hard)
                assert s.score == 0.0
                continue
            assert s.score == pytest.approx(1.0 - expected_loss(t)), (ep["id"], dp, s.components)
    assert checked > 0


def only_exact(t, s):
    return set(s.hard_zeroing) <= EXACT


def test_wrong_action_type_also_zeroes_destination(zpack, zscorer):
    W = zpack.weights

    def mutate(o, t):
        o["action"]["type"] = "resolve" if t["action_type"] != "resolve" else "ask_clarifying"

    _check(zpack, zscorer, mutate, lambda t: W["action_type"] + W["destination"], hard_ok=only_exact)


def test_wrong_destination(zpack, zscorer):
    def mutate(o, t):
        key = "escalate_to" if t["action_type"] == "escalate" else "queue"
        o["action"][key] = "general_support" if t[key] != "general_support" else "tax_ops"

    _check(zpack, zscorer, mutate, lambda t: zpack.weights["destination"],
           applies=lambda t: t["action_type"] in ("route", "escalate"), hard_ok=only_exact)  # fmt: skip


def test_invented_queue_on_non_routing_action(zpack, zscorer):
    def mutate(o, t):
        o["action"]["queue"] = "general_support"

    _check(zpack, zscorer, mutate, lambda t: zpack.weights["destination"],
           applies=lambda t: t["action_type"] not in ("route", "escalate"))  # fmt: skip


def test_wrong_priority_no_adjacent_credit(zpack, zscorer):
    order = ["P0", "P1", "P2", "P3"]

    def mutate(o, t):
        p = t["priority"]
        o["action"]["priority"] = order[(order.index(p) + 1) % 4] if p else "P2"

    _check(zpack, zscorer, mutate, lambda t: zpack.weights["priority"], hard_ok=only_exact)


def test_forbidden_flag_zeroes_flags(zpack, zscorer):
    def mutate(o, t):
        o["action"]["flags"].append(t["forbidden_flags"][0])

    _check(
        zpack, zscorer, mutate, lambda t: zpack.weights["flags"], applies=lambda t: bool(t["forbidden_flags"])
    )


def test_missing_required_flag_costs_f1(zpack, zscorer):
    W = zpack.weights["flags"]

    def mutate(o, t):
        o["action"]["flags"] = list(t["required_flags"])[1:]

    def loss(t):
        n = len(t["required_flags"])
        if n == 1:
            return W
        p, r = 1.0, (n - 1) / n
        return W * (1 - 2 * p * r / (p + r))

    _check(zpack, zscorer, mutate, loss, applies=lambda t: bool(t["required_flags"]),
           hard_ok=lambda t, s: only_exact(t, s) and t["required_flags"][0] in ("fraud_claim", "regulatory_complaint"))  # fmt: skip


def test_extra_flag_when_none_required(zpack, zscorer):
    def mutate(o, t):
        o["action"]["flags"] = [next(f for f in sorted(zpack.flags) if f not in t["forbidden_flags"])]

    _check(
        zpack, zscorer, mutate, lambda t: zpack.weights["flags"], applies=lambda t: not t["required_flags"]
    )


def test_nonexistent_policy_zeroes_citation(zpack, zscorer):
    def mutate(o, t):
        o["action"]["policy_ids"].append("ZZZ-99")

    _check(zpack, zscorer, mutate, lambda t: zpack.weights["policy_citation"])


def test_unacceptable_policy_costs_precision(zpack, zscorer):
    def mutate(o, t):
        acc = set(t["may_cite"]) | set(t["must_cite"])
        o["action"]["policy_ids"].append(next(p for p in sorted(zpack.policy_ids) if p not in acc))

    def loss(t):
        n = len(set(t["must_cite"]))
        return zpack.weights["policy_citation"] * (1 - n / (n + 1))

    _check(zpack, zscorer, mutate, loss, applies=lambda t: bool(t["must_cite"]))


def test_extra_acceptable_policy_is_free(zpack, zscorer):
    def mutate(o, t):
        o["action"]["policy_ids"].append(sorted(set(t["may_cite"]) - set(t["must_cite"]))[0])

    _check(zpack, zscorer, mutate, lambda t: 0.0,
           applies=lambda t: bool(set(t["may_cite"]) - set(t["must_cite"])))  # fmt: skip


def test_missing_required_policy_costs_recall(zpack, zscorer):
    W = zpack.weights["policy_citation"]

    def mutate(o, t):
        o["action"]["policy_ids"] = list(t["must_cite"])[1:]

    _check(zpack, zscorer, mutate, lambda t: W if len(t["must_cite"]) == 1 else W / len(t["must_cite"]),
           applies=lambda t: bool(t["must_cite"]))  # fmt: skip


def test_missing_ask_costs_its_fraction(zpack, zscorer):
    def mutate(o, t):
        o["reply"] = " ".join([NEUTRAL, *(ASK_SENTENCES[k] for k in t["must_ask"][1:])])

    def loss(t):
        # some ask sentences satisfy two keys (a bank-last-four ask also verifies identity)
        reply = " ".join([NEUTRAL, *(ASK_SENTENCES[k] for k in t["must_ask"][1:])])
        got = sum(asked(zpack, reply, k) for k in t["must_ask"])
        return zpack.weights["must_ask"] * (1 - got / len(t["must_ask"]))

    _check(zpack, zscorer, mutate, loss, applies=lambda t: bool(t["must_ask"]))


# ---------------------------------------------------------------------------- hard criteria
def _first(zpack, pred, split="train"):
    return next((ep, dp, t, c) for ep, dp, t, c in all_decisions(zpack, split) if pred(t))


def test_h1_disclosure_only_when_gate_live(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: not t["may_disclose_account_details"])
    o = gold_obj(t)
    o["reply"] += " Your current balance is $18,211.40."
    s = score(zscorer, o, t, c)
    assert "H1_disclosure_before_verification" in s.hard_zeroing and s.score == 0.0
    ep, dp, t, c = _first(zpack, lambda t: t["may_disclose_account_details"])
    o = gold_obj(t)
    o["reply"] += " Your current balance is $18,211.40."
    assert score(zscorer, o, t, c).hard["H1_disclosure_before_verification"] == []


def test_h1_quoting_the_customer_is_not_disclosure(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: not t["may_disclose_account_details"])
    o = gold_obj(t)
    o["reply"] += " You mentioned a transfer of $2,400."
    assert score(zscorer, o, t, c + ["There's a $2,400 transfer I didn't make."]).hard_zeroing == []


def test_h2_fraud_not_p0(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: "fraud_claim" in t["required_flags"])
    o = gold_obj(t)
    o["action"]["priority"] = "P1"
    assert score(zscorer, o, t, c).hard_zeroing == ["H2_fraud_not_immediate"]


def test_h3_regulatory_routed_not_escalated(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: "regulatory_complaint" in t["required_flags"])
    o = gold_obj(t)
    o["action"].update(type="route", queue="compliance", escalate_to=None)
    assert "H3_regulatory_not_escalated" in score(zscorer, o, t, c).hard_zeroing


def test_h4_advice(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: True)
    o = gold_obj(t)
    o["reply"] += " Honestly, I'd recommend selling the position before the close."
    assert "H4_advice_given" in score(zscorer, o, t, c).hard_zeroing


def test_h5_commitment_fires_but_explanation_is_free(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: not t["allowed_timeline_claims"])
    o = gold_obj(t)
    o["reply"] += " We'll have this resolved within 2 business days."
    assert "H5_unstated_timeline" in score(zscorer, o, t, c).hard_zeroing
    o = gold_obj(t)
    o["reply"] += " There is no committed timeline for this, so I can't promise 2 business days."
    assert score(zscorer, o, t, c).hard_zeroing == []


def test_neutral_margin_options_are_not_advice_but_steering_is(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: True)
    o = gold_obj(t)
    o["reply"] += (
        " A call can be met by depositing funds, depositing marginable securities, or closing positions."
    )
    assert score(zscorer, o, t, c).hard["H4_advice_given"] == []
    for steer in (" Depositing funds is usually the safer choice.", " Or you could sell half of your holdings.",
                  " Closing the XYZ position would cover it."):  # fmt: skip
        o = gold_obj(t)
        o["reply"] += " You can deposit funds or close positions." + steer
        assert "H4_advice_given" in score(zscorer, o, t, c).hard_zeroing, steer


def test_hour_on_a_derived_date_is_unstated(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: "3 business days" in t["allowed_timeline_claims"])
    base = " Settlement takes 3 business days, so the funds will be released"
    o = gold_obj(t)
    o["reply"] += base + " on Thursday."
    assert score(zscorer, o, t, c).hard_zeroing == []
    for tail in (" by 5 pm on Thursday.", " by the end of the business day on Thursday."):
        o = gold_obj(t)
        o["reply"] += base + tail
        assert "H5_unstated_timeline" in score(zscorer, o, t, c).hard_zeroing, tail


def test_pack_clock_time_always_allowed(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: not t["allowed_timeline_claims"])
    o = gold_obj(t)
    o["reply"] += " Wires will go out by 2 pm ET."
    assert score(zscorer, o, t, c).hard["H5_unstated_timeline"] == []


def test_advisory_reports_but_does_not_zero(zpack, zscorer):
    ep, dp, t, c = _first(zpack, lambda t: True)
    o = gold_obj(t)
    o["reply"] += " You should sell half of it now."
    s = score(zscorer, o, t, c, advisory=frozenset({"H4_advice_given"}))
    assert s.hard["H4_advice_given"] and s.hard_zeroing == [] and s.score == pytest.approx(1.0)


def test_exact_criteria_cannot_be_advisory(zscorer):
    with pytest.raises(ValueError):
        zscorer.check_advisory(["H2"])


def test_hard_violation_zeroes_whole_episode(zpack, zscorer):
    ep = next(e for e in load_split(zpack, "dev") if len(e["decisions"]) >= 2)
    resp = [json.dumps(gold_obj(ep["decisions"][d])) for d in ep["decisions"]]
    bad = json.loads(resp[-1])
    bad["reply"] += " My advice is to sell everything today."
    resp[-1] = json.dumps(bad)
    r = zscorer.score_episode(ep, resp)
    assert r.hard_failed and r.reward == 0.0 and r.decisions[0].score == pytest.approx(1.0)


def test_format_failure_zeroes_that_decision_only(zpack, zscorer):
    ep = next(e for e in load_split(zpack, "dev") if len(e["decisions"]) >= 2)
    resp = [json.dumps(gold_obj(ep["decisions"][d])) for d in ep["decisions"]]
    resp[0] = "```json\n" + resp[0] + "\n```"
    r = zscorer.score_episode(ep, resp)
    assert not r.decisions[0].format_valid and r.decisions[0].format_diagnostics.get("fenced_json")
    assert r.reward == pytest.approx((len(resp) - 1) / len(resp))


def test_missing_turn_scores_zero(zpack, zscorer):
    ep = next(e for e in load_split(zpack, "dev") if len(e["decisions"]) >= 2)
    first = next(iter(ep["decisions"]))
    r = zscorer.score_episode(ep, [json.dumps(gold_obj(ep["decisions"][first]))])
    assert r.missing_decisions == len(ep["decisions"]) - 1
    assert r.reward == pytest.approx(1 / len(ep["decisions"]))


def test_standing_flags_are_neutral_on_follow_ups(zpack, zscorer):
    n = 0
    for split in ("train", "dev"):
        for ep in load_split(zpack, split):
            dps = list(ep["decisions"])
            for i, dp in enumerate(dps[1:], 1):
                prior = [ep["decisions"][d] for d in dps[:i]]
                standing = set().union(*(set(p["required_flags"]) for p in prior
                                         if p["action_type"] in ("route", "escalate"))) & zpack.standing_flags  # fmt: skip
                t = ep["decisions"][dp]
                extra = sorted(standing - set(t["required_flags"]) - set(t["forbidden_flags"]))
                if not extra:
                    continue
                resp = [json.dumps(gold_obj(ep["decisions"][d])) for d in dps]
                o = json.loads(resp[i])
                o["action"]["flags"] += extra
                resp[i] = json.dumps(o)
                assert zscorer.score_episode(ep, resp).reward == pytest.approx(1.0), (ep["id"], dp)
                n += 1
    assert n > 0


def test_v5_ask_gate_zeroes_the_decision_not_the_episode(zpack):
    v5 = Scorer(Pack(zpack.root, "v5"))
    ep = next(e for e in load_split(zpack, "train")
              if len(e["decisions"]) >= 2 and next(iter(e["decisions"].values()))["action_type"] == "ask_verification")  # fmt: skip
    resp = [json.dumps(gold_obj(ep["decisions"][d])) for d in ep["decisions"]]
    o = json.loads(resp[0])
    o["action"]["type"] = "resolve"
    resp[0] = json.dumps(o)
    r4 = Scorer(zpack).score_episode(ep, resp)
    r5 = v5.score_episode(ep, resp)
    assert r4.decisions[0].score > 0 and r4.decisions[0].missed_ask
    assert r5.decisions[0].score == 0.0 and r5.decisions[0].gates == ["ask_gate"]
    assert not r5.hard_failed and r5.decisions[1].score == pytest.approx(1.0)
    assert r5.config_version == "fst-scorer-v5"


def test_must_ask_patterns_never_leak_between_packs(tmp_path):
    """Regression: compiled must_ask patterns were once cached by id(pack). After a Pack was
    garbage-collected, a new Pack could reuse its id and silently score with another project's
    patterns (v5 re-scoring of the 9B base read 0.525 instead of 0.526, depending on test order)."""
    import gc

    from helpers import ZOOMBERG
    from supportrl.runs import load_outputs, score_outputs, summarise
    from supportrl.scaffold import init_project

    def v5_9b():
        p = Pack(ZOOMBERG, "v5")
        rows, _ = load_outputs(ZOOMBERG / "results/test/qwen3.5-9b-base")
        eps = {e["id"]: e for e in load_split(p, "test", allow_locked=True)}
        return round(summarise(p, score_outputs(p, eps, rows))["composite"], 3)

    starter = init_project(tmp_path / "s")
    for _ in range(20):  # create and drop packs with different identity_verification patterns
        sp = Pack(starter)
        assert asked(sp, "Could you confirm the postcode?", "identity_verification")
        del sp
        gc.collect()
        assert v5_9b() == 0.526
    zp = Pack(ZOOMBERG)
    assert not asked(zp, "Could you confirm the postcode?", "identity_verification")
