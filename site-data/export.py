#!/usr/bin/env python3
"""Turn saved eval outputs into JSON the demo site replays. Schema: site-data/README.md.

    python site-data/export.py site-data/zoomberg.yaml          # every export listed there
    python site-data/export.py --project examples/zoomberg --split test \
        --run base-9b="Qwen3.5-9B base"=examples/zoomberg/results/test/qwen3.5-9b-base \
        --out site-data/out/custom.json

No model calls: every score is recomputed from the saved outputs with the project's
scoring config (or a named variant), so adding a model (v2) means adding one run entry.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from supportrl.pack import Pack
from supportrl.sitedata import export

HERE = Path(__file__).resolve().parent


def run_one(
    project: str, split: str, runs: list[dict], out: Path, scoring: str | None, advisory, base: Path
) -> None:
    pack = Pack(base / project, scoring)
    runs = [{**r, "path": str(base / r["path"])} for r in runs]
    data = export(pack, split, runs, advisory)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    comps = ", ".join(f"{m['key']} {m['summary']['composite']:.3f}" for m in data["models"])
    print(f"wrote {out} ({len(data['episodes'])} episodes; {comps})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("config", nargs="?", help="YAML listing exports (see site-data/zoomberg.yaml)")
    ap.add_argument("--project")
    ap.add_argument("--split")
    ap.add_argument("--scoring")
    ap.add_argument("--run", action="append", default=[], help="key=label=RUN_DIR")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.config:
        cfg = yaml.safe_load(open(a.config))
        base = Path(a.config).resolve().parent
        for ex in cfg["exports"]:
            run_one(ex["project"], ex["split"], ex["runs"], base / ex["out"], ex.get("scoring"),
                    ex.get("advisory"), base)  # fmt: skip
        return 0
    if not (a.project and a.split and a.run and a.out):
        ap.error("give a config file, or --project --split --run ... --out")
    runs = []
    for spec in a.run:
        key, label, path = spec.split("=", 2)
        runs.append({"key": key, "label": label, "path": path})
    run_one(a.project, a.split, runs, Path(a.out), a.scoring, None, Path.cwd())
    return 0


if __name__ == "__main__":
    sys.exit(main())
