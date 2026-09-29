"""A verifiers ``MultiTurnEnv``: scripted customer follow-ups, reward = the supportrl scorer.

Built on the classic ``vf.MultiTurnEnv`` / ``load_environment`` API, which is the same in
verifiers 0.2.x and 0.3.x. A hosted trainer runs its own verifiers build, so the stable
surface is the one to target, and the package requires ``verifiers>=0.2.0`` rather than
pinning it (pinning downgrades the trainer's own install).

Rollout: system = instructions + policy pack; user = session context + the first customer
turn. After each assistant turn the next scripted customer turn is injected; the rollout
stops when every decision point has a response. Model input never includes the episode id,
family, difficulty, split, labels or rationales: those stay in the rubric, keyed by id.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset

from supportrl.data import SplitLocked, first_user_message, followups, load_split, shuffled_passes
from supportrl.pack import COMPONENTS, Pack
from supportrl.scorer import SCORER_VERSION, Scorer

logger = logging.getLogger(__name__)
_STATE_KEY = "supportrl"
BUNDLED = Path(__file__).resolve().parent / "project"


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(getattr(p, "text", "") or "") for p in content
        )
    return str(content)


def _get(obj: Any, key: str, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def assistant_texts(completion: Any) -> list[str]:
    if isinstance(completion, str):
        return [completion]
    return [_text(_get(m, "content")) for m in (completion or []) if _get(m, "role") == "assistant"]


def _turn_usage(state: dict) -> list[dict]:
    out = []
    for step in state.get("trajectory") or []:
        resp = step.get("response")
        usage, msg = _get(resp, "usage"), _get(resp, "message")
        reasoning = _get(msg, "reasoning_content") or ""
        out.append({
            "prompt_tokens": _get(usage, "prompt_tokens"),
            "completion_tokens": _get(usage, "completion_tokens"),
            "reasoning_tokens": _get(usage, "reasoning_tokens"),
            "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0,
            "finish_reason": _get(msg, "finish_reason"),
            "truncated": bool(step.get("is_truncated")),
        })  # fmt: skip
    return out


class SupportRubric(vf.Rubric):
    """Reward = episode score. Everything else is a zero-weight metric on the dashboard."""

    METRICS = (
        "format_invalid_rate", "hard_fail", "graded_mean",
        "over_escalation_rate", "under_escalation_rate", "under_route_rate",
        "missed_ask_rate", "over_ask_rate", "missing_decisions",
        "max_completion_tokens", "truncated_turns", "thinking_turns",
    )  # fmt: skip

    def __init__(self, pack: Pack, episodes: dict[str, dict], advisory, **kwargs):
        super().__init__(**kwargs)
        self.pack, self.episodes = pack, episodes
        self.scorer = Scorer(pack)
        self.advisory = self.scorer.check_advisory(advisory)
        self.add_reward_func(self.support_reward, weight=1.0)
        names = [
            *self.METRICS,
            *(f"comp_{k}" for k in COMPONENTS),
            *(f"hard_{h.short}" for h in pack.hard_criteria),
        ]
        for name in names:
            self.add_metric(self._metric(name), weight=0.0)

    def _evaluate(self, completion, info, state) -> dict:
        cached = state.get(_STATE_KEY)
        if cached is not None:
            return cached
        if isinstance(info, str):
            info = json.loads(info)
        ep = self.episodes[info["episode_id"]]
        result = self.scorer.score_episode(ep, assistant_texts(completion), self.advisory).to_dict()
        result["usage"] = _turn_usage(state)
        result["family"], result["difficulty"] = ep["family"], ep["difficulty"]
        state[_STATE_KEY] = result
        return result

    async def support_reward(self, completion, info, state, **kwargs) -> float:
        return float(self._evaluate(completion, info, state)["reward"])

    def _metric(self, name: str):
        codes = {f"hard_{h.short}": h.code for h in self.pack.hard_criteria}

        async def metric(completion, info, state, **kwargs) -> float:
            r = self._evaluate(completion, info, state)
            ds = r["decisions"]
            n = len(ds) or 1
            usage = r["usage"]
            if name == "format_invalid_rate":
                return sum(not d["format_valid"] for d in ds) / n
            if name == "hard_fail":
                return float(r["hard_failed"])
            if name == "graded_mean":
                return sum(d["graded"] for d in ds) / n
            if name.startswith("comp_"):
                return sum(d["components"][name[5:]] for d in ds) / n
            if name in codes:
                return float(sum(bool(d["hard"][codes[name]]) for d in ds))
            if name.endswith("_rate"):
                return sum(bool(d[name[: -len("_rate")]]) for d in ds) / n
            if name == "missing_decisions":
                return float(r["missing_decisions"])
            if name == "max_completion_tokens":
                return float(max((u["completion_tokens"] or 0 for u in usage), default=0))
            if name == "truncated_turns":
                return float(sum(u["truncated"] or u["finish_reason"] == "length" for u in usage))
            if name == "thinking_turns":
                # Thinking should be OFF. A turn that reasoned anyway is a sampling-transport
                # problem; surface it instead of letting it silently eat the token budget.
                return float(
                    sum((u["reasoning_tokens"] or 0) > 0 or u["reasoning_chars"] > 0 for u in usage)
                    + sum("<think>" in t for t in assistant_texts(completion))
                )
            raise KeyError(name)

        metric.__name__ = name
        return metric


class SupportEnv(vf.MultiTurnEnv):
    """Scripted multi-turn: the next customer turn is injected after each assistant turn."""

    def __init__(self, episodes: list[dict], **kwargs):
        self._script = {e["id"]: followups(e) for e in episodes}
        self._n = {e["id"]: len(e["decisions"]) for e in episodes}
        super().__init__(**kwargs)

    @staticmethod
    def _eid(state) -> str:
        info = state.get("info") or {}
        return (json.loads(info) if isinstance(info, str) else info)["episode_id"]

    @vf.stop
    async def all_decisions_made(self, state) -> bool:
        return len(state["trajectory"]) >= self._n[self._eid(state)]

    async def env_response(self, messages, state, **kwargs):
        k = len(state["trajectory"])
        script = self._script[self._eid(state)]
        if k - 1 < len(script):
            return [{"role": "user", "content": script[k - 1]}]
        state["final_env_response"] = []
        return []


def build_dataset(pack: Pack, episodes: list[dict]) -> Dataset:
    # No `task` column: newer verifiers read `task` as a serialized task payload.
    return Dataset.from_list(
        [
            {
                "prompt": [{"role": "user", "content": first_user_message(pack, e)}],
                "answer": "",
                "info": {"episode_id": e["id"]},
            }
            for e in episodes
        ]  # fmt: skip
    )


def load_environment(
    project: str | None = None,
    split: str = "train",
    allow_locked: bool = False,
    advisory_hard: list[str] | None = None,
    scoring: str | None = None,
    max_episodes: int | None = None,
    repeats: int = 1,
    shuffle_seed: int = 0,
    **kwargs,
) -> vf.Environment:
    """
    project        path to a support-rl project; default: the project bundled by `supportrl env build`
    split          a split or subset name from supportrl.yaml (train, dev, dev_val, test, ...)
    allow_locked   required to load a locked split (the frozen test set)
    advisory_hard  hard criteria reported but not zeroing (detectors below the probe recall floor)
    scoring        a named scoring variant from supportrl.yaml (default: `scoring`)
    max_episodes   first N episodes by id (smoke runs)
    repeats        TRAIN ONLY: N independently shuffled passes, so a hosted sampler that reads
                   tasks in order neither runs out nor sees one family per batch
    """
    pack = Pack(project or BUNDLED, scoring)
    if split in pack.splits and pack.splits[split].locked and not allow_locked:
        raise SplitLocked(
            f"split {split!r} is locked; pass allow_locked=true for the approved final eval only"
        )
    episodes = load_split(pack, split, allow_locked=allow_locked)
    if max_episodes is not None:
        episodes = episodes[:max_episodes]
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if repeats > 1 and split != "train":
        raise ValueError("repeats is for the train split only; evaluation splits stay one pass in id order")
    rows = shuffled_passes(episodes, repeats, shuffle_seed) if repeats > 1 else episodes
    dataset = build_dataset(pack, rows)
    rubric = SupportRubric(pack, {e["id"]: e for e in episodes}, advisory_hard)
    logger.info("supportrl env project=%s split=%s episodes=%d scorer=%s/%s", pack.name, split,
                len(episodes), SCORER_VERSION, pack.scorer_version)  # fmt: skip
    return SupportEnv(
        episodes,
        dataset=dataset,
        eval_dataset=dataset,  # same configured split either way: a runner can only see what its config names
        system_prompt=pack.system_prompt(),
        rubric=rubric,
        max_turns=max(len(e["decisions"]) for e in episodes),
        **kwargs,
    )
