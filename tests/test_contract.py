import json

import pytest

from supportrl.contract import parse

OK = {"reply": "Hi.", "action": {"type": "resolve", "queue": None, "escalate_to": None, "priority": None,
                                  "flags": [], "policy_ids": []}}  # fmt: skip


def test_valid(zpack):
    assert parse(json.dumps(OK), zpack).ok
    assert parse("\n  " + json.dumps(OK) + "\n", zpack).ok


@pytest.mark.parametrize(
    "wrap", ["Sure! {j}", "{j} Let me know.", "```json\n{j}\n```", "<think>hmm</think>{j}", "{j}{j}", "[{j}]"]
)
def test_whole_response_only(zpack, wrap):
    assert not parse(wrap.format(j=json.dumps(OK)), zpack).ok


def test_fence_and_think_are_diagnosed_not_rescued(zpack):
    p = parse("```json\n" + json.dumps(OK) + "\n```", zpack)
    assert not p.ok and p.diagnostics.get("fenced_json")
    assert parse("<think>x</think>" + json.dumps(OK), zpack).diagnostics.get("think_tag")


def test_duplicate_keys_rejected(zpack):
    dup = '{"reply": "a", "reply": "b", "action": ' + json.dumps(OK["action"]) + "}"
    assert parse(dup, zpack).error == "duplicate_key:reply"


@pytest.mark.parametrize("field,val", [("type", "transfer"), ("queue", "billing"), ("priority", "P4"),
                                        ("flags", ["urgent"]), ("policy_ids", "IDV-01")])  # fmt: skip
def test_vocab(zpack, field, val):
    o = json.loads(json.dumps(OK))
    o["action"][field] = val
    assert not parse(json.dumps(o), zpack).ok


def test_keys(zpack):
    o = json.loads(json.dumps(OK))
    del o["action"]["escalate_to"]
    assert not parse(json.dumps(o), zpack).ok
    o = json.loads(json.dumps(OK))
    o["action"]["reason"] = "x"
    assert not parse(json.dumps(o), zpack).ok
    o = json.loads(json.dumps(OK))
    o["reply"] = "   "
    assert not parse(json.dumps(o), zpack).ok
    assert parse("", zpack).error == "empty_response" and parse(None, zpack).error == "empty_response"


def test_unknown_policy_id_is_not_a_format_failure(zpack):
    o = json.loads(json.dumps(OK))
    o["action"]["policy_ids"] = ["ZZZ-99"]
    assert parse(json.dumps(o), zpack).ok
