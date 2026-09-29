"""``supportrl report``: a markdown before/after table from saved runs.

Every run is re-scored from its saved outputs with the project's current scoring config, so
the columns are always comparable. The first run is the reference: each other column gets a
paired per-episode bootstrap of its composite difference (95% CI) and a better / worse /
unchanged episode count. With 32 test episodes one decision moves the composite by ~0.02, so
read component-level differences as noise unless the interval says otherwise.
"""

from __future__ import annotations

import random
from math import fsum
from pathlib import Path

from .data import load_split
from .pack import COMPONENTS, Pack
from .runs import load_outputs, score_outputs, summarise


def paired_bootstrap(a: dict[str, float], b: dict[str, float], n: int = 10000, seed: int = 0) -> dict:
    ids = sorted(set(a) & set(b))
    diffs = [b[i] - a[i] for i in ids]
    if not diffs:
        return {"n": 0}
    rng = random.Random(seed)
    k = len(diffs)
    means = sorted(fsum(diffs[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return {
        "n": k,
        "delta": fsum(diffs) / k,
        "lo": means[int(0.025 * n)],
        "hi": means[int(0.975 * n) - 1],
        "better": sum(d > 1e-9 for d in diffs),
        "worse": sum(d < -1e-9 for d in diffs),
        "same": sum(abs(d) <= 1e-9 for d in diffs),
    }


def load_run(pack: Pack, path: str | Path, split: str | None = None, advisory=None) -> dict:
    rows, meta = load_outputs(path)
    split = split or meta.get("split")
    if not split:
        raise ValueError(f"{path}: meta.json has no split; pass --split")
    eps = {e["id"]: e for e in load_split(pack, split, allow_locked=True)}
    scored = score_outputs(pack, eps, rows)
    label = meta.get("label") or meta.get("model") or Path(path).name
    return {
        "label": label,
        "path": str(path),
        "split": split,
        "summary": summarise(pack, scored, advisory),
        "rewards": {s["episode_id"]: s["reward"] for s in scored},
    }


def render(pack: Pack, runs: list[dict], title: str | None = None) -> str:
    f3 = lambda x: "–" if x is None else f"{x:.3f}"  # noqa: E731
    head = "| | " + " | ".join(r["label"] for r in runs) + " |"
    sep = "|---|" + "---|" * len(runs)
    s = [r["summary"] for r in runs]
    splits = sorted({r["split"] for r in runs})
    lines = [f"### {title or pack.title}", "",
             f"Split: {', '.join(splits)} · {s[0]['episodes']} episodes / {s[0]['decisions']} decisions · "
             f"scoring `{pack.scorer_version}`", "", head, sep]  # fmt: skip

    def row(name, vals):
        lines.append(f"| {name} | " + " | ".join(vals) + " |")

    row("**Composite** (a hard violation zeroes the episode)", [f"**{f3(x['composite'])}**" for x in s])
    if any(x["composite_advisory"] is not None for x in s):
        adv = "/".join(next(x["advisory"] for x in s if x["advisory"]))
        row(f"Composite, {adv} advisory", [f3(x["composite_advisory"]) for x in s])
    row("Composite, no hard gate", [f3(x["composite_no_hard_gate"]) for x in s])
    row("Episodes hard-failed", [f"{x['episodes_hard_failed']} / {x['episodes']}" for x in s])
    for c in COMPONENTS:
        row(c.replace("_", " "), [f3(x["components"][c]) for x in s])
    for h in pack.hard_criteria:
        row(f"{h.short} {h.description or h.code}", [str(x["hard_violations"][h.short]) for x in s])
    gates = sorted({g for x in s for g in x["gates"]})
    for g in gates:
        row(f"decisions zeroed by {g}", [str(x["gates"].get(g, 0)) for x in s])
    row("Format failures", [f"{x['format_invalid']} / {x['decisions']}" for x in s])
    row("Over-escalation rate", [f3(x["over_escalation_rate"]) for x in s])
    row("Under-route rate (resolved a routable matter)", [f3(x["under_route_rate"]) for x in s])
    if pack.ask_types:
        row("Missed-ask rate", [f3(x["missed_ask_rate"]) for x in s])
    diffs = sorted({k for x in s for k in x["by_difficulty"]})
    if diffs:
        row(" / ".join(diffs), [" / ".join(f3(x["by_difficulty"].get(d)) for d in diffs) for x in s])
    if len(runs) > 1:
        ref = runs[0]
        vals = ["(reference)"]
        for r in runs[1:]:
            b = paired_bootstrap(ref["rewards"], r["rewards"])
            vals.append(
                f"{b['delta']:+.3f} [{b['lo']:+.3f}, {b['hi']:+.3f}]; {b['better']}↑ {b['worse']}↓ {b['same']}="
                if b["n"] else "no shared episodes"
            )  # fmt: skip
        row("Δ composite vs first column, paired bootstrap 95% CI", vals)
    lines.append("")
    types = sorted({t for x in s for t in x["action_type_correct"]})
    lines += ["Correct action type, by target type:", "", head.replace("| |", "| target |"), sep]
    for t in types:
        row(t, [x["action_type_correct"].get(t, "–") for x in s])
    return "\n".join(lines) + "\n"
