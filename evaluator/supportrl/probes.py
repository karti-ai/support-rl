"""Measure detector recall and precision on hand-labelled probe sets.

Probe files live in the project's ``probes/`` directory, named ``<code>.<part>.jsonl``
(``h4.dev.jsonl``, ``h4.holdout.jsonl``, ``h4.holdout-v2.jsonl``). One probe per line::

    {"id": "H4-DEV-01", "detector": "H4", "label": "violation" | "clean",
     "reply": "...",
     "customer": ["customer turns so far"],            # optional
     "context": {"account_masked": "****1234"},        # optional (or account_masked at top level)
     "target": {"allowed_timeline_claims": [...]},     # optional (or the field at top level)
     "pair": "A"}                                      # optional matched pair

* **dev** probes are for developing a detector; they grow with every fix.
* **holdout** probes are written before the detector is run on them and are never used to
  change it. Quote holdout numbers. Once a holdout has been used to fix a detector, write a
  new versioned holdout (``holdout-v2``) and quote its *first* measurement.

A detector whose recall on any set is below ``scoring.probe_recall_floor`` (default 0.9) is
reported as advisory: runs publish the composite with and without it.

**Seen holdouts.** If a holdout set was used to fix a detector after its first measurement,
record that first measurement in ``probes/first-measurements.yaml``::

    h4.holdout-v2.jsonl: {recall: 0.50, precision: 1.00, n: 12, note: "..."}

The report then quotes the first measurement as the holdout figure (and uses it for the
advisory decision), and shows today's figure only as "post-fix, seen".
"""

from __future__ import annotations

import json
from pathlib import Path

from .data import read_jsonl
from .detectors import DetectorInput
from .pack import Pack
from .scorer import Scorer


def _input(p: dict) -> DetectorInput:
    ctx = dict(p.get("context") or {})
    if "account_masked" in p:
        ctx.setdefault("account_masked", p["account_masked"])
    target = dict(p.get("target") or {})
    if "allowed_timeline_claims" in p:
        target.setdefault("allowed_timeline_claims", p["allowed_timeline_claims"])
    return DetectorInput(p["reply"], list(p.get("customer") or []), ctx, target)


def probe_files(pack: Pack) -> list[Path]:
    return sorted(pack.probes_dir.glob("*.jsonl")) if pack.probes_dir.exists() else []


def measure(pack: Pack, scorer: Scorer, path: Path) -> dict:
    rows = read_jsonl(path)
    tp = fp = fn = tn = 0
    wrong = []
    fired: dict[str, bool] = {}
    code = None
    for p in rows:
        code = pack.resolve_code(p["detector"])
        hits = scorer.detector(code).detect(_input(p))
        pred, gold = bool(hits), p["label"] == "violation"
        fired[p["id"]] = pred
        tp += pred and gold
        fp += pred and not gold
        fn += gold and not pred
        tn += not pred and not gold
        if pred != gold:
            wrong.append(
                {"id": p["id"], "label": p["label"], "reply": p["reply"], "hits": [str(h) for h in hits]}
            )
    pairs: dict[str, list[dict]] = {}
    for p in rows:
        if p.get("pair"):
            pairs.setdefault(p["pair"], []).append(p)
    return {
        "file": path.name,
        "code": code,
        "holdout": ".holdout" in path.name,
        "n": len(rows),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "recall": tp / (tp + fn) if tp + fn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "pairs": len(pairs),
        "pairs_separated": sum(
            all(fired[m["id"]] == (m["label"] == "violation") for m in ms) for ms in pairs.values()
        ),
        "misclassified": wrong,
    }  # fmt: skip


FIRST = "first-measurements.yaml"


def first_measurements(pack: Pack) -> dict:
    path = pack.probes_dir / FIRST
    if not path.exists():
        return {}
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def report(pack: Pack) -> dict:
    scorer = Scorer(pack)
    sets = [measure(pack, scorer, f) for f in probe_files(pack)]
    firsts = first_measurements(pack)
    for s in sets:
        first = firsts.get(s["file"])
        s["seen"] = first is not None
        s["first_measurement"] = first
        # the figure to quote: a seen holdout's first measurement, otherwise today's
        s["quoted_recall"] = first["recall"] if first else s["recall"]
        s["quoted_precision"] = first.get("precision") if first else s["precision"]
    advisory = sorted(
        {
            s["code"]
            for s in sets
            if s["quoted_recall"] is None or s["quoted_recall"] < pack.probe_recall_floor
        }
    )
    covered = {s["code"] for s in sets}
    unmeasured = [h.code for h in pack.hard_criteria if h.detector and h.code not in covered]
    return {
        "scoring_config": pack.scorer_version,
        "recall_floor": pack.probe_recall_floor,
        "sets": sets,
        "advisory": advisory,
        "unmeasured_detectors": unmeasured,
    }


def format_report(r: dict, verbose: bool = False) -> str:
    f = lambda x: "  n/a" if x is None else f"{x:5.2f}"  # noqa: E731
    lines = [f"{'probe set':24s} {'n':>3s}  recall  precision  tp fp fn tn"]
    for s in r["sets"]:
        pairs = f"  pairs {s['pairs_separated']}/{s['pairs']}" if s["pairs"] else ""
        if s.get("seen"):
            fm = s["first_measurement"]
            lines.append(
                f"{s['file']:24s} {fm.get('n', s['n']):3d}  {f(fm['recall'])}   {f(fm.get('precision'))}"
                "    first measurement (quote this)"
            )
            lines.append(
                f"{'':24s} {s['n']:3d}  {f(s['recall'])}   {f(s['precision'])}    "
                f"{s['tp']:2d} {s['fp']:2d} {s['fn']:2d} {s['tn']:2d}  post-fix, seen: not a holdout figure{pairs}"
            )
            continue
        lines.append(
            f"{s['file']:24s} {s['n']:3d}  {f(s['recall'])}   {f(s['precision'])}    "
            f"{s['tp']:2d} {s['fp']:2d} {s['fn']:2d} {s['tn']:2d}{pairs}"
        )
        if verbose:
            for w in s["misclassified"]:
                lines.append(f"    MISS {w['id']} [{w['label']}] {w['reply'][:100]}")
                lines.extend(f"         hit {h[:110]}" for h in w["hits"])
    lines.append(
        f"advisory (quoted recall < {r['recall_floor']} on any set): "
        + (", ".join(r["advisory"]) if r["advisory"] else "none")
    )
    if r["unmeasured_detectors"]:
        lines.append("WARNING no probe set measures: " + ", ".join(r["unmeasured_detectors"]))
    return "\n".join(lines)


def dump(r: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(r, indent=2) + "\n")
