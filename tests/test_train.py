import json
import tomllib

from helpers import ZOOMBERG, gold_obj
from supportrl.data import load_split
from supportrl.pack import Pack
from supportrl_train import prime, select, trl_grpo


def test_decision_rows_never_leak_labels(zpack):
    rows = trl_grpo.decision_rows(zpack, "train", "gold")
    assert len(rows) == 77  # one prompt per train decision
    eps = {e["id"]: e for e in load_split(zpack, "train")}
    for r in rows:
        text = json.dumps(r["prompt"])
        assert r["episode_id"] not in text
        dp = r["decision_point"]
        assert eps[r["episode_id"]]["decisions"][dp]["rationale"][:60] not in text
        # the prompt ends at the customer's turn for this decision
        assert r["prompt"][-1]["role"] == "user"
        assert sum(m["role"] == "assistant" for m in r["prompt"]) == int(dp[1:]) - 1


def test_reward_function_scores_gold_one(zpack):
    rows = trl_grpo.decision_rows(zpack, "train", "gold")
    reward = trl_grpo.DecisionReward(zpack)
    eps = reward.episodes
    comps = [
        [{"content": json.dumps(gold_obj(eps[r["episode_id"]]["decisions"][r["decision_point"]]))}]
        for r in rows
    ]
    got = reward(comps, [r["episode_id"] for r in rows], [r["decision_point"] for r in rows])
    assert all(abs(g - 1.0) < 1e-9 for g in got)
    assert reward([[{"content": "not json"}]], [rows[0]["episode_id"]], [rows[0]["decision_point"]]) == [0.0]


def test_trl_dry_run(capsys):
    assert trl_grpo.main([str(ZOOMBERG), "--model", "x", "--output-dir", "unused", "--dry-run"]) == 0
    assert "77 decision prompts" in capsys.readouterr().out


def test_selection_rule_ties_go_later():
    assert select.choose({"step7": 0.644, "step14": 0.786, "step21": 0.514}) == "step14"
    assert select.choose({"checkpoint-25": 0.7, "checkpoint-50": 0.7}) == "checkpoint-50"


def test_select_from_saved_candidates(zpack):
    r = select.from_runs(
        zpack, {f"step{s}": str(ZOOMBERG / f"results/dev_val/v1-candidate-step{s:02d}") for s in (7, 14, 21)}
    )
    assert select.choose(r) == "step14" and round(r["step14"], 3) == 0.786


def test_prime_config_renders(tmp_path):
    run = prime.prepare(str(ZOOMBERG), "Qwen/Qwen3.5-9B", "me", str(tmp_path))
    cfg = tomllib.loads(run.config.read_text())
    assert cfg["model"] == "Qwen/Qwen3.5-9B" and cfg["max_steps"] == 21 and cfg["rollouts_per_example"] == 8
    assert cfg["env"][0]["args"] == {"split": "train", "repeats": 8, "shuffle_seed": 0}
    assert cfg["eval"]["env"][0]["args"] == {"split": "dev_val"}
    assert cfg["sampling"]["enable_thinking"] is False
    # the locked test split is not shipped in the hosted environment package
    data = run.env_dir / "zoomberg_support_triage" / "project" / "data"
    assert sorted(p.name for p in data.iterdir()) == ["train.jsonl", "validation.jsonl"]
    assert run.commands[0][:3] == ["prime", "env", "push"]
    assert Pack(run.env_dir / "zoomberg_support_triage" / "project").scorer_version == "fst-scorer-v4"


def test_ask_guard_passes_and_single_pass_default(zpack):
    """Guard off by default; with a guard, a candidate that asks at least as well survives."""
    R = ZOOMBERG / "results" / "dev_val_v2"
    v5 = Pack(ZOOMBERG, "v5")
    p = lambda n: [str(R / f"{n}-p{k}") for k in (1, 2, 3)]  # noqa: E731
    res = select.select_runs(v5, {"base": p("qwen3.5-9b-base"), "v1": p("support-9b-v1")}, "dev_val_v2")
    assert all(c["passes_guard"] is None for c in res["candidates"].values()) and res["selected"] == "v1"
    res = select.select_runs(v5, {"base": p("qwen3.5-9b-base"), "v1": p("support-9b-v1")}, "dev_val_v2",
                             p("qwen3.5-9b-base"))  # fmt: skip
    assert res["candidates"]["base"]["passes_guard"] and not res["candidates"]["v1"]["passes_guard"]
    assert res["selected"] == "base" and not res["guard_all_failed"]
    import pytest

    with pytest.raises(ValueError, match="no"):  # dev_val (splits-v1) has no ask targets
        select.select_runs(v5, {"x": [str(ZOOMBERG / "results/dev_val/v1-candidate-step14")]}, "dev_val",
                           [str(ZOOMBERG / "results/dev_val/v1-candidate-step07")])  # fmt: skip
