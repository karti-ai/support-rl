"""Hosted LoRA RL on Prime Intellect.

    supportrl train examples/zoomberg --backend prime --model Qwen/Qwen3.5-9B --owner <your-hub-user>

1. ``supportrl env build`` writes a self-contained environment package (scorer + project).
2. A run config is rendered from ``templates/prime-rl.toml`` into ``runs/train/<name>/``.
3. The two commands are printed: ``prime env push`` (from the built package) and
   ``prime train <config>``. Pass ``--launch`` to run them. The ``prime`` CLI must be
   installed and logged in, and the run bills your Prime account.

Defaults are the settings that trained Karti-Small-Support-9B v1 (56 train episodes,
21 steps, 8 rollouts per episode at T=1.0, batch 64, lr 1e-4, LoRA alpha 16, 512 max
tokens, thinking off, dev_val monitored and adapters kept every 7 steps). That run cost $5.45
of training plus ~$0.14 of evaluation. Estimate yours before launching: cost scales with
steps x batch x tokens per rollout.
"""

from __future__ import annotations

import math
import shlex
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from supportrl.data import load_split
from supportrl.envbuild import build_env
from supportrl.pack import Pack


@dataclass
class PrimeRun:
    config: Path
    env_dir: Path
    commands: list[list[str]]


def render(pack: Pack, model: str, owner: str, name: str, env_name: str, env_version: str, *,
           max_steps: int = 21, batch_size: int = 64, rollouts: int = 8, lr: float = 1e-4, lora_alpha: int = 16,
           max_tokens: int = 512, temperature: float = 1.0, interval: int = 7, shuffle_seed: int = 0) -> str:  # fmt: skip
    n_train = len(load_split(pack, "train"))
    groups_needed = max_steps * max(1, batch_size // rollouts)
    repeats = max(1, math.ceil(2.5 * groups_needed / max(1, n_train)))  # comfortable headroom
    sel = pack.selection.get("subset", "dev_val")
    tmpl = (resources.files("supportrl_train") / "templates" / "prime-rl.toml").read_text()
    return tmpl.format(
        name=name, model=model, max_steps=max_steps, batch_size=batch_size, rollouts=rollouts, lr=lr,
        lora_alpha=lora_alpha, max_tokens=max_tokens, temperature=temperature,
        env_id=f"{owner}/{env_name}@{env_version}", repeats=repeats, shuffle_seed=shuffle_seed,
        interval=interval, selection_subset=sel, project=pack.name, n_train=n_train,
    )  # fmt: skip


def prepare(project: str, model: str, owner: str, out_root: str = "runs/train", name: str | None = None,
            env_version: str = "0.1.0", **kw) -> PrimeRun:  # fmt: skip
    pack = Pack(project)
    short = model.split("/")[-1].lower()
    name = name or f"{pack.name}-{short}-lora"
    env_name = f"{pack.name}-support-triage"
    run_dir = Path(out_root) / name
    run_dir.mkdir(parents=True, exist_ok=True)
    env_dir = build_env(project, run_dir / "env", name=env_name, version=env_version)
    cfg = run_dir / "prime-rl.toml"
    cfg.write_text(render(pack, model, owner, name, env_name, env_version, **kw))
    return PrimeRun(
        config=cfg,
        env_dir=env_dir,
        commands=[
            ["prime", "env", "push", "--path", str(env_dir), "--visibility", "PRIVATE"],
            ["prime", "train", str(cfg)],
        ],
    )


def launch(run: PrimeRun) -> None:
    for cmd in run.commands:
        print("$", shlex.join(cmd), flush=True)
        subprocess.run(cmd, check=True)
