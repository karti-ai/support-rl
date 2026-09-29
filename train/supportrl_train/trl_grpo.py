"""Self-hosted GRPO + LoRA with TRL on a single GPU.

    pip install -e ".[train]"
    supportrl train examples/zoomberg --backend trl --model Qwen/Qwen3.5-4B --output-dir runs/trl-4b

What it does
------------
Each **decision point** of each train episode becomes one GRPO prompt: the system prompt
(instructions + policy pack), the session context, and the conversation up to that
decision. The reward is the supportrl scorer's decision score (format gate, hard criteria,
graded components). Extra dataset columns carry the episode id and decision point to the
reward function; labels never enter the prompt.

**One real difference from the hosted backend.** The hosted environment is multi-turn and
on-policy: at d2 the model sees its *own* d1 reply. TRL's standard GRPO loop generates one
completion per prompt, so earlier agent turns here are filled from a *history source*:

  --history gold          (default) the labelled action of each earlier decision, with a short
                          neutral reply. Teacher forcing: clean, but the model never trains
                          on recovering from its own earlier mistake.
  --history <run dir>     the replies a model actually gave in a saved run on the train
                          split (``supportrl baseline ... --split train``). Off-policy but realistic.

Single-decision episodes are identical under both. Evaluation and checkpoint selection are
always multi-turn and on-policy (``supportrl_train.select``).

Hardware
--------
bf16 LoRA, one GPU, 8 generations per prompt, 512 completion tokens, gradient checkpointing:

  Qwen3.5-4B   ~24 GB  (a 24 GB card is tight: lower --num-generations or --max-completion-length first)
  Qwen3.5-9B   ~80 GB  (A100/H100 80 GB)

These are planning figures, not measurements from this repo's CI (which has no GPU).

Qwen3.5 specifics
-----------------
* Qwen3.5 checkpoints are ``Qwen3_5ForConditionalGeneration`` (image-text-to-text), with the
  language model under ``model.language_model.*``. Load them with
  ``AutoModelForImageTextToText``. ``AutoModelForCausalLM`` builds a different module tree:
  an adapter trained on the real tree matches none of its modules, so PEFT attaches no LoRA
  and you silently get the base model back. This script picks the class from the config,
  and ``select`` uses the same rule when it loads checkpoints.
* Thinking is **off**: ``chat_template_kwargs={"enable_thinking": False}`` in training,
  selection and evaluation alike. A model trained with thinking off must be served with it off.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from supportrl.data import customer_texts_by_decision, first_user_message, followups, load_split
from supportrl.pack import Pack
from supportrl.runs import load_outputs
from supportrl.scorer import Scorer

NEUTRAL_REPLY = "Thank you. I have recorded this."


def gold_turn(target: dict) -> str:
    return json.dumps({
        "reply": NEUTRAL_REPLY,
        "action": {
            "type": target["action_type"], "queue": target.get("queue"), "escalate_to": target.get("escalate_to"),
            "priority": target.get("priority"), "flags": list(target.get("required_flags") or []),
            "policy_ids": list(target.get("must_cite") or []),
        },
    })  # fmt: skip


def decision_rows(pack: Pack, split: str = "train", history: str = "gold") -> list[dict]:
    """One row per decision point: {prompt: [messages], episode_id, decision_point}."""
    episodes = load_split(pack, split)
    saved = {}
    if history != "gold":
        rows, _ = load_outputs(history)
        saved = {r["episode_id"]: r["responses"] for r in rows}
        missing = [e["id"] for e in episodes if e["id"] not in saved and len(e["decisions"]) > 1]
        if missing:
            print(
                f"warning: the history run has no replies for {len(missing)} multi-decision {split} episodes "
                f"(e.g. {missing[0]}); their later decisions are dropped",
                file=sys.stderr,
            )
    out = []
    for ep in episodes:
        script = followups(ep)
        dps = list(ep["decisions"])
        msgs = [{"role": "system", "content": pack.system_prompt()},
                {"role": "user", "content": first_user_message(pack, ep)}]  # fmt: skip
        for k, dp in enumerate(dps):
            out.append({"prompt": [dict(m) for m in msgs], "episode_id": ep["id"], "decision_point": dp})
            if k < len(dps) - 1:
                if history == "gold":
                    prev = gold_turn(ep["decisions"][dp])
                else:
                    got = saved.get(ep["id"], [])
                    if k >= len(got):
                        break  # the saved run has no reply here; later decisions have no history
                    prev = got[k]
                msgs += [{"role": "assistant", "content": prev}, {"role": "user", "content": script[k]}]
    return out


class DecisionReward:
    """TRL reward function: completions -> supportrl decision scores."""

    __name__ = "supportrl_decision_reward"

    def __init__(self, pack: Pack, split: str = "train"):
        self.pack, self.scorer = pack, Scorer(pack)
        self.episodes = {e["id"]: e for e in load_split(pack, split)}
        self.seen = {i: customer_texts_by_decision(e) for i, e in self.episodes.items()}

    def standing(self, ep: dict, dp: str) -> frozenset[str]:
        flags: set[str] = set()
        for d in ep["decisions"]:
            if d == dp:
                break
            t = ep["decisions"][d]
            if t["action_type"] in ("route", "escalate"):
                flags |= set(t.get("required_flags") or []) & self.pack.standing_flags
        return frozenset(flags)

    def __call__(self, completions, episode_id, decision_point, **kwargs) -> list[float]:
        out = []
        for comp, eid, dp in zip(completions, episode_id, decision_point):
            text = comp[0]["content"] if isinstance(comp, list) else comp
            ep = self.episodes[eid]
            s = self.scorer.score_decision(dp, ep["decisions"][dp], text, self.seen[eid][dp], ep["context"],
                                           frozenset(), self.standing(ep, dp))  # fmt: skip
            out.append(float(s.score))
        return out


def model_class_for(model_id: str):
    from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForImageTextToText

    cfg = AutoConfig.from_pretrained(model_id)
    arch = " ".join(getattr(cfg, "architectures", None) or [])
    if "ConditionalGeneration" in arch or getattr(cfg, "model_type", "").startswith("qwen3_5"):
        return AutoModelForImageTextToText
    return AutoModelForCausalLM


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="supportrl train --backend trl", description=__doc__.split("\n\n")[0])
    ap.add_argument("project")
    ap.add_argument("--model", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--history", default="gold", help="gold, or a saved run dir on the train split")
    ap.add_argument("--max-steps", type=int, default=150)
    ap.add_argument("--num-generations", type=int, default=8)
    ap.add_argument(
        "--per-device-batch", type=int, default=8, help="prompts x generations must divide evenly"
    )
    ap.add_argument("--grad-accum", type=int, default=1)
    ap.add_argument("--learning-rate", type=float, default=1e-5)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=16)
    ap.add_argument("--max-completion-length", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--save-steps", type=int, default=25)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="build the dataset and check the reward; no torch")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    pack = Pack(a.project)
    rows = decision_rows(pack, "train", a.history)
    reward = DecisionReward(pack)
    gold = reward([[{"content": gold_turn(reward.episodes[r["episode_id"]]["decisions"][r["decision_point"]])}]
                   for r in rows], [r["episode_id"] for r in rows], [r["decision_point"] for r in rows])  # fmt: skip
    print(f"{len(rows)} decision prompts from {len({r['episode_id'] for r in rows})} train episodes "
          f"(history={a.history}); mean reward of the labelled action with a neutral reply: "
          f"{sum(gold) / len(gold):.3f}")  # fmt: skip
    if a.dry_run:
        print(
            json.dumps({k: v for k, v in rows[-1].items() if k != "prompt"}),
            "prompt messages:",
            len(rows[-1]["prompt"]),
        )
        return 0

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer
    from trl import GRPOConfig, GRPOTrainer

    tok = AutoTokenizer.from_pretrained(a.model)
    model = model_class_for(a.model).from_pretrained(a.model, dtype=torch.bfloat16, device_map="auto")
    peft_config = LoraConfig(
        r=a.lora_r, lora_alpha=a.lora_alpha, lora_dropout=0.0, bias="none", task_type="CAUSAL_LM",
        # language-model projections only; vision tower (if any) untouched
        target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
        if "ImageTextToText" in type(model).__name__ else ["q_proj", "k_proj", "v_proj", "o_proj",
                                                            "gate_proj", "up_proj", "down_proj"],
    )  # fmt: skip
    args = GRPOConfig(
        output_dir=a.output_dir,
        max_steps=a.max_steps,
        learning_rate=a.learning_rate,
        per_device_train_batch_size=a.per_device_batch,
        gradient_accumulation_steps=a.grad_accum,
        num_generations=a.num_generations,
        max_completion_length=a.max_completion_length,
        temperature=a.temperature,
        chat_template_kwargs={"enable_thinking": False},
        gradient_checkpointing=True,
        bf16=True,
        save_steps=a.save_steps,
        save_only_model=True,
        logging_steps=1,
        seed=a.seed,
        report_to="none",
    )
    trainer = GRPOTrainer(
        model=model,
        reward_funcs=reward,
        args=args,
        train_dataset=Dataset.from_list(rows),
        processing_class=tok,
        peft_config=peft_config,
    )
    trainer.train()
    trainer.save_model(str(Path(a.output_dir) / "final"))
    print(f"adapters in {a.output_dir}/checkpoint-*; select with: supportrl train {a.project} "
          f"--backend select --model {a.model} --checkpoints {a.output_dir}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
