"""Export saved runs as JSON a demo site can replay (schema: site-data/README.md).

Per episode: the conversation, the labels for each decision, and for every model its raw
output, the parsed reply and action, component scores, hard-criterion hits and gates.
Everything is recomputed from saved outputs with the project's scoring config; no model is
called.
"""

from __future__ import annotations

import re

from .contract import parse
from .data import load_split
from .pack import Pack
from .runs import load_outputs, score_outputs, summarise

SCHEMA = "supportrl-site-data/1"
LABEL_KEYS = (
    "action_type", "queue", "escalate_to", "priority", "required_flags", "forbidden_flags",
    "must_cite", "may_cite", "must_ask", "prohibited", "allowed_timeline_claims",
)  # fmt: skip
_TITLE = re.compile(r"\*\*([A-Z]{2,5}-\d{2,3}) — ([^*]+?)\.?\*\*")


def policy_titles(pack: Pack) -> dict[str, str]:
    return {pid: title.strip() for pid, title in _TITLE.findall(pack.policy_text)}


def rounded(obj, ndigits: int = 6):
    """Round every float, so the export is byte-stable across Python versions (3.12 changed
    ``sum()`` to compensated summation: 0.5515625 vs 0.5515625000000001 on 3.11)."""
    if isinstance(obj, float):
        return round(obj, ndigits) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(obj, dict):
        return {k: rounded(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [rounded(v, ndigits) for v in obj]
    return obj


def export(pack: Pack, split: str, runs: list[dict], advisory: list[str] | None = None) -> dict:
    """``runs``: [{"key", "label", "path", "description"?}] in display order."""
    episodes = load_split(pack, split, allow_locked=True)
    eps = {e["id"]: e for e in episodes}
    per_model = {}
    models = []
    for r in runs:
        rows, meta = load_outputs(r["path"])
        rows = [x for x in rows if x["episode_id"] in eps]
        scored = score_outputs(pack, eps, rows)
        per_model[r["key"]] = ({x["episode_id"]: x for x in rows}, {s["episode_id"]: s for s in scored})
        s = summarise(pack, scored, advisory)
        models.append({
            "key": r["key"],
            "label": r.get("label") or meta.get("model") or r["key"],
            "description": r.get("description", ""),
            "model": meta.get("model"),
            "sampling": meta.get("sampling"),
            "summary": {k: s[k] for k in (
                "episodes", "decisions", "composite", "composite_advisory", "advisory", "composite_no_hard_gate",
                "episodes_hard_failed", "components", "hard_violations", "gates", "format_invalid",
                "over_escalation_rate", "under_escalation_rate", "under_route_rate", "missed_ask_rate",
                "action_type_correct", "by_difficulty", "by_family")},
        })  # fmt: skip
    short = {h.code: h.short for h in pack.hard_criteria}
    out_eps = []
    for ep in episodes:
        decs = []
        for i, (dp, target) in enumerate(ep["decisions"].items()):
            entry = {
                "decision_point": dp,
                "target": {k: target.get(k) for k in LABEL_KEYS}
                | {k: v for k, v in target.items() if isinstance(v, bool)}
                | {"rationale": target.get("rationale")},
                "models": {},
            }
            for key, (rows, scored) in per_model.items():
                if ep["id"] not in rows:
                    continue
                raw = rows[ep["id"]]["responses"][i] if i < len(rows[ep["id"]]["responses"]) else None
                d = scored[ep["id"]]["decisions"][i]
                p = parse(raw, pack)
                entry["models"][key] = {
                    "raw": raw,
                    "format_valid": d["format_valid"],
                    "format_error": d["format_error"],
                    "reply": p.output.reply if p.ok else None,
                    "action": p.output.action.to_dict() if p.ok else None,
                    "components": d["components"],
                    "graded": round(d["graded"], 6),
                    "score": round(d["score"], 6),
                    "hard_hits": [
                        {"code": c, "short": short[c], "evidence": ev, "zeroing": c in d["hard_zeroing"]}
                        for c, ev in d["hard"].items()
                        if ev
                    ],  # fmt: skip
                    "gates": d.get("gates") or [],
                }
            decs.append(entry)
        out_eps.append({
            "id": ep["id"],
            "family": ep["family"],
            "difficulty": ep["difficulty"],
            "context": ep["context"],
            "turns": [{"t": t["t"], "role": t["role"], "text": t.get("text"), "decision_point": t.get("decision_point")}
                      for t in ep["turns"]],
            "decisions": decs,
            "results": {key: {"reward": round(scored[ep["id"]]["reward"], 6), "hard_failed": scored[ep["id"]]["hard_failed"]}
                        for key, (_, scored) in per_model.items() if ep["id"] in scored},
        })  # fmt: skip
    return rounded({
        "schema": SCHEMA,
        "project": {"name": pack.name, "title": pack.title, "scoring": pack.scorer_version,
                    "prompt_version": pack.prompt_version, "policy_pack_sha256": pack.sha256()["policy_pack"]},
        "split": split,
        "data_license": pack.data_license or None,
        "weights": pack.weights,
        "hard_criteria": [{"code": h.code, "short": h.short, "description": h.description,
                           "kind": "exact" if h.is_exact else "detector"} for h in pack.hard_criteria],
        "policies": policy_titles(pack),
        "models": models,
        "episodes": out_eps,
    })  # fmt: skip
