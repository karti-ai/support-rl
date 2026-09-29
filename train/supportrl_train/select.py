"""Checkpoint selection on the project's selection subset (``dev_val``), multi-turn, on-policy.

    supportrl train examples/zoomberg --backend select --model Qwen/Qwen3.5-4B --checkpoints runs/trl-4b
    supportrl train examples/zoomberg --backend select --candidates step7=runs/dv-7 step14=runs/dv-14

Two ways in:

* ``--checkpoints DIR``: every ``checkpoint-*`` adapter under DIR is loaded on the base model
  with transformers, and the selection subset is rolled out locally (T=0, thinking off,
  the project's max_tokens). Needs the ``train`` extra and a GPU.
* ``--candidates name=RUN ...``: runs you already produced, e.g. by serving each adapter
  (``vllm serve ... --lora-modules``) and running ``supportrl eval --split dev_val``. Scored
  from their saved outputs; no GPU needed.

Options for ``--candidates`` (both default off):

* **multi-pass**: ``name=RUN1,RUN2,RUN3`` gives several independent T=0 passes per candidate;
  the rule uses their mean and the report shows the spread. Hosted T=0 serving is not
  deterministic, so a single pass on a 9-episode subset can move by ~0.1.
* **ask guard**: ``--ask-guard RUN1,RUN2,RUN3`` (a reference model's passes, usually the base)
  rejects any candidate whose pooled ask accuracy is below the reference's. Use it with a
  selection subset that contains ask targets (``--subset``).

The rule is the one declared in supportrl.yaml before training (``selection``): the highest
composite with every hard criterion zeroing; ties go to the later step. The locked test split
is never touched here.
"""

from __future__ import annotations

import re
from math import fsum
from pathlib import Path

from supportrl.client import Completion
from supportrl.data import load_split
from supportrl.pack import Pack
from supportrl.rollout import run_many
from supportrl.runs import base_meta, load_outputs, score_outputs, summarise, write_run


def _step(name: str) -> int:
    m = re.search(r"(\d+)(?!.*\d)", name)
    return int(m.group(1)) if m else -1


def choose(results: dict[str, float]) -> str:
    """Highest composite; ties go to the later step."""
    return max(results, key=lambda k: (round(results[k], 10), _step(k)))


def _pass(pack: Pack, eps: dict[str, dict], name: str, path: str, subset: str) -> dict:
    rows, meta = load_outputs(path)
    rows = [r for r in rows if r["episode_id"] in eps]
    if {r["episode_id"] for r in rows} != set(eps):
        raise ValueError(f"{name}: run {path} does not cover every {subset} episode")
    scored = score_outputs(pack, eps, rows)
    decs = [d for s in scored for d in s["decisions"]]
    asks = [d for d in decs if d["target_action_type"] in pack.ask_types]
    return {
        "path": str(path),
        "composite": summarise(pack, scored)["composite"],
        "ask_right": sum(d["model_action_type"] == d["target_action_type"] for d in asks),
        "ask_n": len(asks),
        "hard_failed": sum(bool(s["hard_failed"]) for s in scored),
    }


def summarise_passes(pack: Pack, paths: list[str], subset: str, name: str = "") -> dict:
    eps = {e["id"]: e for e in load_split(pack, subset)}
    ps = [_pass(pack, eps, name, p, subset) for p in paths]
    comps = [p["composite"] for p in ps]
    ask_n = sum(p["ask_n"] for p in ps)
    ask_right = sum(p["ask_right"] for p in ps)
    return {
        "passes": ps,
        "mean_composite": fsum(comps) / len(comps),
        "spread": max(comps) - min(comps),
        "ask_pooled": f"{ask_right}/{ask_n}",
        "ask_accuracy": ask_right / ask_n if ask_n else None,
    }


def select_runs(pack: Pack, candidates: dict[str, list[str]], subset: str | None = None,
                ask_guard: list[str] | None = None) -> dict:  # fmt: skip
    """Selection from saved runs, optionally multi-pass and ask-guarded.

    ``candidates``: name -> one or more runs of that candidate on the selection subset. With
    several runs (independent passes at T=0: hosted serving is not deterministic) the rule uses
    the mean composite, and reports the per-pass spread.

    ``ask_guard``: runs of a reference model (usually the base) on the same subset. A candidate
    whose pooled ask accuracy (ask decisions answered with the target ask type, over all its
    passes) is below the reference's is rejected. If every candidate is rejected, the highest
    mean composite is still returned, with ``guard_all_failed`` set, so the failure is reported
    rather than hidden. The subset must contain ask targets for the guard to mean anything.
    """
    subset = subset or pack.selection.get("subset", "dev_val")
    out: dict = {
        "subset": subset,
        "reference": None,
        "candidates": {},
        "selected": None,
        "guard_all_failed": False,
    }
    bar = None
    if ask_guard:
        ref = summarise_passes(pack, ask_guard, subset, "reference")
        if ref["ask_accuracy"] is None:
            raise ValueError(f"--ask-guard needs ask targets in {subset!r}, and it has none")
        out["reference"], bar = ref, ref["ask_accuracy"]
    for name, paths in candidates.items():
        c = summarise_passes(pack, paths, subset, name)
        c["passes_guard"] = None if bar is None else (c["ask_accuracy"] or 0.0) >= bar - 1e-12
        out["candidates"][name] = c
    names = list(out["candidates"])
    ok = [n for n in names if out["candidates"][n]["passes_guard"] is not False]
    out["guard_all_failed"] = bool(names) and not ok
    pool = ok or names
    if pool:
        out["selected"] = choose({n: out["candidates"][n]["mean_composite"] for n in pool})
    return out


def from_runs(pack: Pack, candidates: dict[str, str]) -> dict[str, float]:
    """Single pass per candidate, no guard: name -> composite on the selection subset."""
    res = select_runs(pack, {k: [v] for k, v in candidates.items()})
    return {k: v["mean_composite"] for k, v in res["candidates"].items()}


def report_runs(res: dict, pack: Pack) -> str:
    lines = [f"selection on {res['subset']} ({pack.selection.get('rule', '')}):"]

    def row(label, s, guard=""):
        per = ", ".join(f"{p['composite']:.3f}" for p in s["passes"])
        multi = f"  passes [{per}] spread {s['spread']:.3f}" if len(s["passes"]) > 1 else ""
        return f"  {label:24s} {s['mean_composite']:.3f}{multi}  asks {s['ask_pooled']}{guard}"

    if res["reference"]:
        lines.append(row("reference (guard bar)", res["reference"]))
    for k in sorted(res["candidates"], key=_step):
        c = res["candidates"][k]
        g = "" if c["passes_guard"] is None else ("  guard ok" if c["passes_guard"] else "  GUARD FAIL")
        lines.append(row(k, c, g) + ("   <- selected" if k == res["selected"] else ""))
    if res["guard_all_failed"]:
        lines.append("every candidate failed the ask guard: the selected one is the best composite, and the "
                     "guard failure is a finding to report, not something to hide")  # fmt: skip
    return "\n".join(lines)


class HFGenerate:
    """A local transformers model as a ``generate`` callable (greedy, thinking off)."""

    def __init__(self, model, tokenizer, max_new_tokens: int):
        self.model, self.tok, self.max_new_tokens = model, tokenizer, max_new_tokens

    def __call__(self, messages: list[dict]) -> Completion:
        import torch

        ids = self.tok.apply_chat_template(messages, add_generation_prompt=True, enable_thinking=False,
                                           return_tensors="pt", return_dict=True).to(self.model.device)  # fmt: skip
        with torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=self.max_new_tokens, do_sample=False)
        new = out[0, ids["input_ids"].shape[1] :]
        return Completion(self.tok.decode(new, skip_special_tokens=True),
                          {"completion_tokens": int(new.shape[0]), "finish_reason": None})  # fmt: skip


def from_checkpoints(pack: Pack, base_model: str, ckpt_dir: str, out_root: str) -> dict[str, float]:
    import torch
    from peft import PeftModel
    from transformers import AutoTokenizer

    from .trl_grpo import model_class_for

    subset = pack.selection.get("subset", "dev_val")
    episodes = load_split(pack, subset)
    eps = {e["id"]: e for e in episodes}
    tok = AutoTokenizer.from_pretrained(base_model)
    base = model_class_for(base_model).from_pretrained(base_model, dtype=torch.bfloat16, device_map="auto")
    results = {}
    ckpts = sorted(Path(ckpt_dir).glob("checkpoint-*"), key=lambda p: _step(p.name))
    if not ckpts:
        raise FileNotFoundError(f"no checkpoint-* under {ckpt_dir}")
    for ck in ckpts:
        model = PeftModel.from_pretrained(base, str(ck))
        model.eval()
        gen = HFGenerate(model, tok, int(pack.inference.get("max_tokens", 1024)))
        rows = run_many(pack, episodes, gen, concurrency=1)
        scored = score_outputs(pack, eps, rows)
        summ = summarise(pack, scored)
        write_run(Path(out_root) / f"select-{ck.name}", base_meta(pack, subset, model=f"{base_model} + {ck}"),
                  rows, scored, {"all": summ})  # fmt: skip
        results[ck.name] = summ["composite"]
        base = model.unload()  # detach LoRA before the next checkpoint
    return results


def report(results: dict[str, float], pack: Pack) -> str:
    best = choose(results)
    lines = [f"selection on {pack.selection.get('subset', 'dev_val')} ({pack.selection.get('rule', '')}):"]
    for k in sorted(results, key=_step):
        lines.append(f"  {k:28s} {results[k]:.3f}{'   <- selected' if k == best else ''}")
    return "\n".join(lines)
