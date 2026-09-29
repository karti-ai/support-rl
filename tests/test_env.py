"""The verifiers environment. Skipped when verifiers is not installed (pip install -e '.[env]')."""

import asyncio
import json
import sys

import pytest

from helpers import ZOOMBERG, gold_obj

vf = pytest.importorskip("verifiers")

from supportrl.data import SplitLocked, load_split  # noqa: E402
from supportrl.envbuild import build_env  # noqa: E402
from supportrl.pack import Pack  # noqa: E402
from supportrl_env import load_environment  # noqa: E402


def test_dataset_is_model_input_only():
    env = load_environment(project=str(ZOOMBERG), split="dev")
    rows = env.get_dataset() if hasattr(env, "get_dataset") else env.dataset
    assert len(rows) == 18
    pack = Pack(ZOOMBERG)
    for r in rows:
        text = json.dumps(r["prompt"]) + env.system_prompt
        ep = next(e for e in load_split(pack, "dev") if e["id"] == r["info"]["episode_id"])
        assert ep["id"] not in text
        for d in ep["decisions"].values():
            assert d["rationale"][:60] not in text


def test_locked_and_repeats_guards():
    with pytest.raises(SplitLocked):
        load_environment(project=str(ZOOMBERG), split="test")
    with pytest.raises(ValueError):
        load_environment(project=str(ZOOMBERG), split="dev", repeats=2)
    env = load_environment(project=str(ZOOMBERG), split="train", repeats=3, shuffle_seed=1)
    assert len(env.dataset) == 56 * 3


def test_rubric_rewards_gold():
    env = load_environment(project=str(ZOOMBERG), split="dev_val")
    pack = Pack(ZOOMBERG)
    ep = next(e for e in load_split(pack, "dev_val") if len(e["decisions"]) >= 2)
    completion = [
        {"role": "assistant", "content": json.dumps(gold_obj(ep["decisions"][d]))} for d in ep["decisions"]
    ]
    state = {"trajectory": []}
    from supportrl_env.environment import SupportRubric

    rub = env.rubric
    rub = (
        rub
        if isinstance(rub, SupportRubric)
        else next(x for x in rub.rubrics if isinstance(x, SupportRubric))
    )
    r = asyncio.run(rub.support_reward(completion, {"episode_id": ep["id"]}, state))
    assert r == pytest.approx(1.0)


def test_built_package_is_self_contained(tmp_path, monkeypatch):
    out = build_env(str(ZOOMBERG), str(tmp_path / "pkg"))
    monkeypatch.syspath_prepend(str(out))
    for m in [m for m in sys.modules if m.startswith("zoomberg_support_triage")]:
        del sys.modules[m]
    import zoomberg_support_triage as z

    env = z.load_environment(split="dev_val")
    assert len(env.dataset) == 9
    with pytest.raises(FileNotFoundError):
        z.load_environment(split="test", allow_locked=True)  # not bundled
