import json
import shutil

import pytest

from helpers import ZOOMBERG, gold_obj
from supportrl.data import SplitLocked, load_split, read_jsonl, write_jsonl
from supportrl.pack import ConfigError, Pack
from supportrl.scaffold import init_project
from supportrl.scorer import Scorer
from supportrl.validate import validate


@pytest.fixture
def zcopy(tmp_path):
    d = tmp_path / "z"
    shutil.copytree(ZOOMBERG, d, ignore=shutil.ignore_patterns("results"))
    return d


def test_zoomberg_validates(zpack):
    r = validate(str(ZOOMBERG))
    assert r.ok, r.format()
    assert len(r.warnings) == 7  # the seven intended full-number traps (CND-04)


def _edit_first(path, fn, where=0):
    rows = read_jsonl(path)
    fn(rows[where])
    write_jsonl(path, rows)


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r["decisions"][0].update(required_policy_ids=["IDV-10"], acceptable_policy_ids=["IDV-10"]), "did you mean"),
    (lambda r: r["decisions"][0].update(required_flags=["urgent"]), "not in vocab.flags"),
    (lambda r: r["decisions"][0].update(priority="P2"), "FRD-01"),
    (lambda r: r["decisions"][0].update(queue="compliance"), "FRD-01"),
    (lambda r: r["turns"].append({"t": 2, "role": "agent", "text": None, "decision_point": "d2"}), "consecutive agent"),
    (lambda r: r["context"].update(account_type="crypto"), "account_type"),
    (lambda r: r.update(id="TRAIN-1"), "does not match"),
])  # fmt: skip
def test_label_errors_are_caught(zcopy, mutate, needle):
    _edit_first(zcopy / "data" / "train.jsonl", mutate)  # TST-TRAIN-0001: fraud route P0
    r = validate(str(zcopy))
    assert not r.ok and any(needle in e for e in r.errors), r.errors


def test_follow_up_rule(zcopy):
    # a follow-up that repeats the standing route instead of resolving
    rows = read_jsonl(zcopy / "data" / "train.jsonl")
    ep = next(r for r in rows if len(r["decisions"]) >= 2 and r["decisions"][0]["action_type"] == "route"
              and r["decisions"][1]["action_type"] == "resolve")  # fmt: skip
    d1, d2 = ep["decisions"][0], ep["decisions"][1]
    d2.update(action_type="route", queue=d1["queue"], priority=d1["priority"])
    write_jsonl(zcopy / "data" / "train.jsonl", rows)
    r = validate(str(zcopy))
    assert any("does not outrank the standing" in e for e in r.errors), r.errors


def test_leakage_duplicate_opening(zcopy):
    train = read_jsonl(zcopy / "data" / "train.jsonl")
    test = read_jsonl(zcopy / "data" / "test.jsonl")
    test[0]["turns"][0]["text"] = train[0]["turns"][0]["text"]
    write_jsonl(zcopy / "data" / "test.jsonl", test)
    assert any("duplicates" in e for e in validate(str(zcopy)).errors)


def test_locked_split_refuses(zpack):
    with pytest.raises(SplitLocked):
        load_split(zpack, "test")
    assert len(load_split(zpack, "test", allow_locked=True)) == 32
    dev = {e["id"] for e in load_split(zpack, "dev")}
    val = {e["id"] for e in load_split(zpack, "dev_val")}
    hold = {e["id"] for e in load_split(zpack, "dev_holdout")}
    assert val | hold == dev and not val & hold and len(val) == 9


def test_unreviewed_episodes_are_skipped(zcopy):
    rows = read_jsonl(zcopy / "data" / "train.jsonl")
    cand = json.loads(json.dumps(rows[0]))
    cand.update(id="TST-TRAIN-9999", decisions=[], review={"status": "unreviewed"})
    cand["turns"][0]["text"] = "A brand new candidate opening line."
    write_jsonl(zcopy / "data" / "train.jsonl", rows + [cand])
    assert len(load_split(Pack(zcopy), "train")) == 56
    r = validate(str(zcopy))
    assert r.ok and any("unreviewed" in w for w in r.warnings)


def test_bad_config(zcopy):
    cfg = (zcopy / "supportrl.yaml").read_text().replace("must_ask: 0.10}", "must_ask: 0.30}")
    (zcopy / "supportrl.yaml").write_text(cfg)
    with pytest.raises(ConfigError, match="sum to 1.0"):
        Pack(zcopy)


def test_starter_project_validates_and_gold_scores_one(tmp_path):
    d = init_project(tmp_path / "acme-support")
    r = validate(str(d))
    assert r.ok and not r.warnings, r.format()
    pack = Pack(d)
    assert pack.name == "acme-support"
    sc = Scorer(pack)
    for split in ("train", "dev", "test"):
        for ep in load_split(pack, split, allow_locked=True):
            resp = [json.dumps(gold_obj(ep["decisions"][x])) for x in ep["decisions"]]
            assert sc.score_episode(ep, resp).reward == pytest.approx(1.0), ep["id"]
    with pytest.raises(FileExistsError):
        init_project(d)
