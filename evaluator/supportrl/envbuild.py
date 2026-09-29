"""``supportrl env build``: a self-contained verifiers environment package for one project.

A hosted trainer installs your environment from a package registry and cannot see your
disk, so the package must carry the scorer and the project with it::

    <out>/
      pyproject.toml            name = <env name>; requires verifiers>=0.2.0, pyyaml
      <module>/__init__.py      load_environment(**kw) bound to the bundled project
      <module>/project/         supportrl.yaml, policy pack, prompt, probes, plugins, split files
      supportrl/                the evaluator (vendored copy)
      supportrl_env/            the environment code (vendored copy)

Locked splits (your test set) are left out unless ``include_locked`` is set: the hosted
run trains on train and monitors dev_val, and the test set never needs to leave your machine.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

from .pack import Pack

PYPROJECT = """\
[project]
name = "{name}"
version = "{version}"
description = "{description}"
requires-python = ">=3.11"
# >=, not ==: pinning verifiers downgrades the hosted trainer's own build.
dependencies = ["verifiers>=0.2.0", "pyyaml>=6"]
tags = ["support", "triage", "multi-turn", "rule-based-reward", "train", "eval"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{module}", "supportrl", "supportrl_env"]
"""

INIT = '''"""{name}: support-rl environment for the {title!r} project (built by `supportrl env build`)."""

from pathlib import Path

from supportrl_env.environment import load_environment as _load

PROJECT = Path(__file__).resolve().parent / "project"


def load_environment(**kwargs):
    kwargs.setdefault("project", str(PROJECT))
    return _load(**kwargs)
'''


def package_dir(name: str) -> Path:
    """Where a package's source lives, found WITHOUT importing it: supportrl_env imports
    verifiers at import time, and building the package must not require verifiers."""
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        raise ModuleNotFoundError(f"package {name!r} not found; reinstall with pip install -e .")
    return Path(next(iter(spec.submodule_search_locations)))


def build_env(project: str, out: str, name: str | None = None, version: str = "0.1.0",
              include_locked: bool = False) -> Path:  # fmt: skip
    pack = Pack(project)
    name = name or f"{pack.name}-support-triage"
    module = re.sub(r"[^a-z0-9_]", "_", name.lower())
    out_p = Path(out)
    if out_p.exists():
        shutil.rmtree(out_p)
    mod = out_p / module
    proj = mod / "project"
    proj.mkdir(parents=True)
    # project files: config, pack, prompt, plugins, split files (locked ones excluded by default), probes
    files = [pack.config_path, pack.policy_pack_path, pack.instructions_path]
    files += [pack.root / p for p in pack.plugins]
    for s in pack.splits.values():
        if s.locked and not include_locked:
            continue
        files.append(s.file)
    for f in files:
        dest = proj / f.relative_to(pack.root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    if pack.probes_dir.exists():
        shutil.copytree(pack.probes_dir, proj / pack.probes_dir.relative_to(pack.root))
    for pkg in ("supportrl", "supportrl_env"):
        shutil.copytree(package_dir(pkg), out_p / pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (mod / "__init__.py").write_text(INIT.format(name=name, title=pack.title))
    desc = f"{pack.title}: multi-turn support triage scored by code (support-rl)".replace('"', "'")
    (out_p / "pyproject.toml").write_text(
        PYPROJECT.format(name=name, version=version, module=module, description=desc)
    )
    (out_p / "README.md").write_text(
        f"# {name}\n\nBuilt by `supportrl env build` from project `{pack.name}`.\n\n"
        f"```python\nimport verifiers as vf\nenv = vf.load_environment('{name}', split='train')\n```\n"
    )
    return out_p
