"""``supportrl init``: scaffold a new project from the starter template.

The starter is a small, complete project for a fictional parcel carrier: a 14-policy pack,
the prompt, 15 labelled episodes across train/dev/test, probe sets and a working
``supportrl.yaml``. It validates and scores out of the box, so you can replace it piece by
piece and re-run ``supportrl validate`` after every change.
"""

from __future__ import annotations

import re
import shutil
from importlib import resources
from pathlib import Path


def init_project(dest: str | Path, name: str | None = None, force: bool = False) -> Path:
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()) and not force:
        raise FileExistsError(f"{dest} exists and is not empty (use --force to write into it)")
    name = name or re.sub(r"[^a-z0-9_-]+", "-", dest.resolve().name.lower()).strip("-") or "support"
    src = resources.files("supportrl") / "templates" / "project"
    with resources.as_file(src) as src_path:
        shutil.copytree(src_path, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    cfg = dest / "supportrl.yaml"
    cfg.write_text(cfg.read_text().replace("__NAME__", name))
    (dest / ".gitignore").write_text("runs/\n")
    return dest
