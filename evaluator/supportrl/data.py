"""Episodes: load, split, and turn into model input.

One JSONL row per episode. The record separates **model input** (``context``, ``turns``) from
the **answer key** (``family``, ``difficulty``, ``decisions``). Nothing from the answer key,
and not the episode id, ever reaches the model.

    {"id": "...", "family": "...", "difficulty": "...",
     "context": {...},
     "turns": [{"t": 0, "role": "customer", "text": "...", "decision_point": null},
               {"t": 1, "role": "agent", "text": null, "decision_point": "d1"}, ...],
     "decisions": [{"decision_point": "d1", "action_type": "route", ...}, ...],
     "review": {"status": "reviewed" | "unreviewed", ...}}        # optional

``decisions`` may also be a dict keyed by decision point. Episodes marked
``review.status == "unreviewed"`` (for example, from the LLM customer simulator) are skipped
by every loader until a human has labelled them.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .pack import Pack


class SplitLocked(RuntimeError):
    pass


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: invalid JSON: {exc}") from exc
    return rows


def write_jsonl(path: str | Path, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def decisions_dict(rec: dict, aliases: dict[str, str] | None = None) -> dict[str, dict]:
    """Labels keyed by decision point, with field aliases (dataset name -> supportrl name) applied."""
    d = rec.get("decisions") or {}
    if isinstance(d, list):
        d = {x["decision_point"]: {k: v for k, v in x.items() if k != "decision_point"} for x in d}
    aliases = aliases or {}
    return {dp: {aliases.get(k, k): v for k, v in lab.items()} for dp, lab in dict(d).items()}


def is_reviewed(rec: dict) -> bool:
    return (rec.get("review") or {}).get("status", "reviewed") != "unreviewed"


def normalize(rec: dict, aliases: dict[str, str] | None = None) -> dict:
    """The joined, validated-shape episode the scorer and the rollout use."""
    decisions = decisions_dict(rec, aliases)
    dps = [t["decision_point"] for t in rec["turns"] if t["role"] == "agent"]
    if dps != list(decisions):
        raise ValueError(f"{rec.get('id')}: decision points in turns {dps} != labels {list(decisions)}")
    return {
        "id": rec["id"],
        "context": rec.get("context") or {},
        "turns": rec["turns"],
        "decisions": decisions,
        "family": rec.get("family"),
        "difficulty": rec.get("difficulty"),
    }


def split_names(pack: Pack) -> list[str]:
    return [*pack.splits, *pack.subsets]


def load_split(pack: Pack, name: str, allow_locked: bool = False) -> list[dict]:
    """Episodes of a split or subset, sorted by id.

    A locked split (the frozen before/after measurement) refuses to load unless the caller
    says so explicitly, so a training or selection config can never pick it up by accident.
    """
    if name in pack.subsets:
        sub = pack.subsets[name]
        eps = load_split(pack, sub.split, allow_locked)
        if sub.ids is not None:
            keep = set(sub.ids)
            return [e for e in eps if e["id"] in keep]
        if sub.exclude is not None:
            drop = {e["id"] for e in load_split(pack, sub.exclude, allow_locked)}
            return [e for e in eps if e["id"] not in drop]
        return eps
    if name not in pack.splits:
        raise ValueError(f"unknown split {name!r}; have {split_names(pack)}")
    split = pack.splits[name]
    if split.locked and not allow_locked:
        raise SplitLocked(
            f"split {name!r} is locked: it is the frozen before/after measurement. Pass "
            "allow_locked (CLI: --allow-locked) only for the approved final evaluation, never "
            "for training or checkpoint selection."
        )
    rows = [r for r in read_jsonl(split.file) if is_reviewed(r)]
    return sorted((normalize(r, pack.field_aliases) for r in rows), key=lambda e: e["id"])


# ---------------------------------------------------------------------------- model input
def first_user_message(pack: Pack, episode: dict) -> str:
    first = episode["turns"][0]
    if first["role"] != "customer":
        raise ValueError(f"{episode['id']}: episode must open with a customer turn")
    return pack.render_context(episode["context"]) + pack.customer_header + first["text"]


def followups(episode: dict) -> list[str]:
    """Customer turns after the first decision point, in order: the scripted replay."""
    out, seen_agent = [], False
    for turn in episode["turns"]:
        if turn["role"] == "agent":
            seen_agent = True
        elif seen_agent:
            out.append(turn["text"])
    return out


def customer_texts_by_decision(episode: dict) -> dict[str, list[str]]:
    """For each decision point: the customer turns the agent has seen so far."""
    seen: list[str] = []
    out = {}
    for turn in episode["turns"]:
        if turn["role"] == "customer":
            seen.append(turn["text"])
        else:
            out[turn["decision_point"]] = list(seen)
    return out


def shuffled_passes(episodes: list[dict], repeats: int, seed: int) -> list[dict]:
    """``repeats`` independently shuffled passes (hosted samplers read tasks in order)."""
    rows: list[dict] = []
    for k in range(repeats):
        order = list(episodes)
        random.Random(seed + k).shuffle(order)
        rows.extend(order)
    return rows
