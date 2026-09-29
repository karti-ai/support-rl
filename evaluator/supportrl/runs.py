"""Run records: saved model outputs, their scores, and the summary every run must report.

A run directory::

    runs/<name>/
      meta.json       model, endpoint, sampling, split, pack hashes, scorer version, timestamp
      outputs.jsonl   one row per episode: {"episode_id", "responses": [...], "usage": [...]}
      scores.jsonl    the scorer's full per-decision record for each episode
      summary.json    the metrics below

Outputs are the raw material. Scores are always recomputable from them with any scorer
version (``supportrl eval --replay``), with no model calls.

The composite alone is not a result. A summary reports the composite three ways (as
scored; with low-recall detectors demoted to advisory; with no hard gate), per-component
means, hard violations by code, format failures by kind, over/under-escalation, under-route,
missed/over-ask, the action-type confusion, per-family and per-difficulty composites, and
token statistics (including any turn that reasoned when thinking was meant to be off).
"""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter, defaultdict
from math import fsum
from pathlib import Path

from .data import read_jsonl, write_jsonl
from .pack import COMPONENTS, Pack
from .scorer import SCORER_VERSION, Scorer


# ---------------------------------------------------------------------------- loading outputs
def _assistant_texts(completion) -> list[str]:
    if isinstance(completion, str):
        return [completion]
    out = []
    for m in completion or []:
        if m.get("role") != "assistant":
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
        out.append(c or "")
    return out


def _from_vf_eval_row(r: dict) -> dict:
    """A verifiers ``vf-eval`` results row (``-s`` saved) -> an outputs row."""
    info = r.get("info") or {}
    if isinstance(info, str):
        info = json.loads(info)
    usage = []
    state = r.get("triage") or r.get("supportrl") or {}
    for t in state.get("turn_diagnostics") or []:
        usage.append({k: t.get(k) for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "finish_reason")}
                     | {"reasoning_chars": t.get("reasoning_chars") or 0, "truncated": t.get("is_truncated")})  # fmt: skip
    return {
        "episode_id": info["episode_id"],
        "responses": _assistant_texts(r.get("completion")),
        "usage": usage,
        "error": r.get("error"),
    }


def load_outputs(path: str | Path) -> tuple[list[dict], dict]:
    """Outputs rows + meta from a run dir, an outputs.jsonl, or a vf-eval results.jsonl."""
    p = Path(path)
    meta: dict = {}
    if p.is_dir():
        if (p / "meta.json").exists():
            meta = json.loads((p / "meta.json").read_text())
        if (p / "outputs.jsonl").exists():
            p = p / "outputs.jsonl"
        elif (p / "results.jsonl").exists():
            if (p / "metadata.json").exists():
                vm = json.loads((p / "metadata.json").read_text())
                meta = {"model": vm.get("model"), "split": (vm.get("env_args") or {}).get("split"),
                        "sampling": vm.get("sampling_args"), "source": "vf-eval"}  # fmt: skip
            p = p / "results.jsonl"
        else:
            raise FileNotFoundError(f"{path}: no outputs.jsonl or results.jsonl")
    elif (p.parent / "meta.json").exists():
        meta = json.loads((p.parent / "meta.json").read_text())
    rows = read_jsonl(p)
    if rows and "responses" not in rows[0] and "completion" in rows[0]:
        rows = [_from_vf_eval_row(r) for r in rows]
    return sorted(rows, key=lambda r: r["episode_id"]), meta


# ---------------------------------------------------------------------------- scoring + summary
def score_outputs(pack: Pack, episodes: dict[str, dict], rows: list[dict], advisory=()) -> list[dict]:
    scorer = Scorer(pack)
    scored = []
    for r in rows:
        ep = episodes.get(r["episode_id"])
        if ep is None:
            raise KeyError(f"{r['episode_id']} is not in the loaded split")
        s = scorer.score_episode(ep, r["responses"], advisory).to_dict()
        s["family"], s["difficulty"] = ep["family"], ep["difficulty"]
        s["usage"] = r.get("usage") or []
        s["error"] = r.get("error")
        scored.append(s)
    return scored


def _mean(xs) -> float:
    """Correctly rounded mean (math.fsum), so summaries are identical on every Python version:
    3.12 changed sum() to compensated summation, which moved 0.6375 across a rounding edge."""
    xs = list(xs)
    return fsum(xs) / len(xs)


def _pct(xs: list[float], q: float) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def episode_value(s: dict, advisory: set[str] | None = None, hard_gate: bool = True) -> float:
    """Episode reward recomputed with some hard criteria demoted (or no hard gate at all)."""
    advisory = advisory or set()
    ds = s["decisions"]
    if not ds:
        return 0.0
    if hard_gate and any(set(d["hard_zeroing"]) - advisory for d in ds):
        return 0.0

    def val(d):
        if not d["format_valid"] or d.get("gates"):
            return 0.0
        if hard_gate and set(d["hard_zeroing"]) - advisory:
            return 0.0
        return d["graded"]

    return fsum(val(d) for d in ds) / len(ds)


def summarise(pack: Pack, scored: list[dict], advisory: list[str] | None = None) -> dict:
    decs = [d for s in scored for d in s["decisions"]]
    nd = len(decs) or 1
    codes = [h.code for h in pack.hard_criteria]
    short = {h.code: h.short for h in pack.hard_criteria}
    adv = set(advisory or [])
    usage = [u for s in scored for u in s.get("usage") or []]
    ctoks = [u["completion_tokens"] for u in usage if u.get("completion_tokens") is not None]
    mean = _mean if scored else (lambda xs: None)
    out = {
        "episodes": len(scored),
        "decisions": len(decs),
        "composite": mean([s["reward"] for s in scored]),
        "advisory": sorted(short[c] for c in adv),
        "composite_advisory": mean([episode_value(s, adv) for s in scored]) if adv else None,
        "composite_no_hard_gate": mean([episode_value(s, hard_gate=False) for s in scored]),
        "episodes_hard_failed": sum(bool(s["hard_failed"]) for s in scored),
        "components": {k: fsum(d["components"][k] for d in decs) / nd for k in COMPONENTS},
        "hard_violations": {short[c]: sum(bool(d["hard"].get(c)) for d in decs) for c in codes},
        "gates": dict(Counter(g for d in decs for g in d.get("gates") or [])),
        "format_invalid": sum(not d["format_valid"] for d in decs),
        "format_errors": dict(
            Counter((d["format_error"] or "").split(":")[0] for d in decs if not d["format_valid"])
        ),
        "format_diagnostics": dict(
            Counter(k for d in decs if not d["format_valid"] for k in d["format_diagnostics"])
        ),
        "over_escalation_rate": sum(d["over_escalation"] for d in decs) / nd,
        "under_escalation_rate": sum(d["under_escalation"] for d in decs) / nd,
        "under_route_rate": sum(d["under_route"] for d in decs) / nd,
        "missed_ask_rate": sum(d.get("missed_ask", False) for d in decs) / nd,
        "over_ask_rate": sum(d.get("over_ask", False) for d in decs) / nd,
        "action_type_correct": {},
        "action_confusion": dict(
            Counter(f"{d['target_action_type']}->{d['model_action_type']}" for d in decs)
        ),
        "completion_tokens": {
            "n": len(ctoks),
            "median": statistics.median(ctoks) if ctoks else None,
            "p95": _pct(ctoks, 0.95),
            "max": max(ctoks) if ctoks else None,
        },
        "turns_with_reasoning": sum(
            1 for u in usage if (u.get("reasoning_tokens") or 0) > 0 or (u.get("reasoning_chars") or 0) > 0
        ),
        "truncated_turns": sum(1 for u in usage if u.get("truncated") or u.get("finish_reason") == "length"),
        "missing_decisions": sum(s["missing_decisions"] for s in scored),
        "rollout_errors": sum(1 for s in scored if s.get("error")),
    }
    by_type = defaultdict(lambda: [0, 0])
    for d in decs:
        by_type[d["target_action_type"]][0] += d["model_action_type"] == d["target_action_type"]
        by_type[d["target_action_type"]][1] += 1
    out["action_type_correct"] = {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_type.items())}
    groups = defaultdict(list)
    for s in scored:
        groups[("family", s["family"])].append(s["reward"])
        groups[("difficulty", s["difficulty"])].append(s["reward"])
    for kind in ("family", "difficulty"):
        out[f"by_{kind}"] = {k[1]: round(_mean(v), 4) for k, v in sorted(groups.items()) if k[0] == kind}
    return out


def summarise_run(pack: Pack, split: str, scored: list[dict], advisory: list[str] | None = None) -> dict:
    """The summary, plus one per subset of this split (e.g. dev -> dev_val / dev_holdout)."""
    from .data import load_split

    res = {"all": summarise(pack, scored, advisory)}
    for name, sub in pack.subsets.items():
        if sub.split != split:
            continue
        ids = {e["id"] for e in load_split(pack, name, allow_locked=True)}
        part = [s for s in scored if s["episode_id"] in ids]
        if part:
            res[name] = summarise(pack, part, advisory)
    return res


# ---------------------------------------------------------------------------- writing
def write_run(run_dir: str | Path, meta: dict, rows: list[dict], scored: list[dict], summary: dict) -> Path:
    d = Path(run_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    write_jsonl(d / "outputs.jsonl", rows)
    write_jsonl(d / "scores.jsonl", scored)
    (d / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return d


def base_meta(pack: Pack, split: str, **extra) -> dict:
    return {
        "project": pack.name,
        "split": split,
        "scorer": SCORER_VERSION,
        "scoring_config": pack.scorer_version,
        "prompt_version": pack.prompt_version,
        "sha256": pack.sha256(),
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **extra,
    }


def format_summary(label: str, s: dict) -> str:
    a = s["all"]
    f = lambda x: "n/a" if x is None else f"{x:.3f}"  # noqa: E731
    lines = [
        f"{label}: {a['episodes']} episodes / {a['decisions']} decisions",
        f"  composite            {f(a['composite'])}",
    ]
    if a["composite_advisory"] is not None:
        lines.append(f"  composite ({'/'.join(a['advisory'])} advisory) {f(a['composite_advisory'])}")
    lines += [
        f"  composite, no gate   {f(a['composite_no_hard_gate'])}",
        f"  hard-failed episodes {a['episodes_hard_failed']}   hard hits {a['hard_violations']}"
        + (f"   gates {a['gates']}" if a["gates"] else ""),
        "  components           " + "  ".join(f"{k} {v:.3f}" for k, v in a["components"].items()),
        f"  format invalid       {a['format_invalid']}/{a['decisions']} {a['format_errors'] or ''}",
        f"  over-esc {a['over_escalation_rate']:.3f}  under-esc {a['under_escalation_rate']:.3f}  "
        f"under-route {a['under_route_rate']:.3f}  missed-ask {a['missed_ask_rate']:.3f}  over-ask {a['over_ask_rate']:.3f}",
        f"  by difficulty        {a['by_difficulty']}",
    ]
    if a["turns_with_reasoning"]:
        lines.append(
            f"  WARNING: {a['turns_with_reasoning']} turns carried reasoning (thinking was meant to be off)"
        )
    if a["truncated_turns"]:
        lines.append(f"  WARNING: {a['truncated_turns']} turns hit max_tokens")
    for name, sub in s.items():
        if name != "all":
            lines.append(f"  {name:20s} composite {f(sub['composite'])} ({sub['episodes']} episodes)")
    return "\n".join(lines)
