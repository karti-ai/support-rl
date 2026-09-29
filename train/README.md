# train: hosted RL, self-hosted GRPO, checkpoint selection

Three backends behind one command, `supportrl train PROJECT --backend prime|trl|select`.
Before any of them: `supportrl validate`, `supportrl probes`, and a frozen baseline on dev
(`supportrl baseline`). Decide the selection rule in `supportrl.yaml` (`selection`) before
training. It is not a knob to turn afterwards.

## (a) Hosted LoRA RL on Prime Intellect

```bash
supportrl train examples/zoomberg --backend prime --model Qwen/Qwen3.5-9B --owner <hub-user>
supportrl train examples/zoomberg --backend prime --model Qwen/Qwen3.5-9B --owner <hub-user> --launch
```

The first command builds the environment package (`supportrl env build`, test split
excluded), renders `runs/train/<name>/prime-rl.toml` from
[`supportrl_train/templates/prime-rl.toml`](supportrl_train/templates/prime-rl.toml), and
prints the two commands. `--launch` runs them: `prime env push` (private) and
`prime train`. You need the `prime` CLI, logged in; the run bills your account.

Defaults are the settings that trained Karti-Small-Support-9B v1: 21 steps, batch 64, 8
rollouts per episode at T=1.0, lr 1e-4, LoRA alpha 16, 512 max tokens, thinking off, the
train split in shuffled repeats (computed so the sampler cannot run out), `dev_val`
monitored and an adapter kept every 7 steps. v1 cost **$5.45** of training (estimate from a
short diagnostic run: $8.21). Estimate yours first: cost scales with steps × batch × tokens
per rollout.

Things that went wrong on the way to v1 and are now handled by the template or the env:
a plain-string `task` column that newer verifiers reject (every rollout failed); an
id-sorted train split that gave one family per batch and could be exhausted by the sampler
(fixed with `repeats` + `shuffle_seed`); monitor evals that lag the saved adapters (select
on the adapters themselves, below). A 4B run stalled on the hosted trainer while a 9B run
with the same config completed; if a run makes no policy update after its first steps, stop
it and try the other size before debugging your environment.

## (b) Self-hosted GRPO + LoRA with TRL, one GPU

```bash
pip install -e ".[train]"
supportrl train examples/zoomberg --backend trl --model Qwen/Qwen3.5-4B --dry-run     # no GPU: prompts + reward check
supportrl train examples/zoomberg --backend trl --model Qwen/Qwen3.5-4B --output-dir runs/trl-4b \
    --max-steps 150 --rollouts 8 --learning-rate 1e-5
```

Arguments after the known ones go to
[`supportrl_train/trl_grpo.py`](supportrl_train/trl_grpo.py) (`--history`, `--lora-r`,
`--max-completion-length`, `--save-steps`, ...).

| base model | VRAM (bf16 LoRA, 8 generations, 512 tokens, grad checkpointing) |
|---|---|
| Qwen3.5-4B | ~24 GB (tight on a 24 GB card: lower `--num-generations` or `--max-completion-length` first) |
| Qwen3.5-9B | ~80 GB (A100 / H100 80 GB) |

These are planning figures, not measurements from this repository.

- **Qwen3.5 must load with `AutoModelForImageTextToText`.** The checkpoints are
  `Qwen3_5ForConditionalGeneration`, with the language model under `model.language_model.*`.
  `AutoModelForCausalLM` builds a different module tree: a LoRA adapter trained on the real
  tree matches none of its modules, PEFT attaches nothing, and you silently get the base
  model. The script picks the class from the model config.
- **Thinking off everywhere**: `chat_template_kwargs={"enable_thinking": False}` in training,
  and `enable_thinking=False` in selection and serving. A model trained without thinking,
  served with thinking on, is likely to break the output contract.
- **Decision-level prompts.** TRL's GRPO loop generates one completion per prompt, so each
  decision point becomes one prompt; earlier agent turns come from `--history` (`gold`: the
  labelled action with a neutral reply, the default; or a saved run's real replies on the
  train split). The hosted backend is multi-turn and on-policy instead. Evaluation and
  selection are always multi-turn and on-policy.
- **Status: not yet run on a GPU in this repository.** The dataset builder and reward function
  are tested; the trainer call follows TRL's documented `GRPOTrainer` API. Expect to adjust
  batch sizes for your card.

## (c) Checkpoint selection

```bash
# adapters you trained locally (needs .[train] and a GPU):
supportrl train examples/zoomberg --backend select --model Qwen/Qwen3.5-4B --checkpoints runs/trl-4b
# runs you already produced by serving each adapter and running `supportrl eval --split dev_val`:
supportrl train examples/zoomberg --backend select --candidates step7=runs/dv7 step14=runs/dv14 step21=runs/dv21
```

Two options for `--candidates`, both off by default:

- **Multi-pass**: `step14=RUN1,RUN2,RUN3` gives several independent T=0 passes of one
  candidate; the rule uses the mean and the report shows the spread. Hosted T=0 serving is not
  deterministic: on 9 episodes the same adapter can move by ~0.08 between passes.
- **Ask guard**: `--ask-guard REF1,REF2,REF3` (a reference model's passes, usually the base)
  rejects any candidate whose pooled ask accuracy is below the reference's. If all fail, the
  best composite is still selected and the guard failure is printed, to be reported. Use it
  with a selection subset that contains ask targets (`--subset dev_val_v2` in the example);
  it refuses a subset without any.

The Zoomberg v3 selection is reproduced this way in `examples/zoomberg/README.md`.

The rule: the highest `dev_val` composite with every hard criterion zeroing; ties go to the
later step. `dev_holdout` is reported alongside and never used to choose; the locked test
split is never touched. Then run the chosen model on test **once**:
`supportrl eval PROJECT --model ... --split test --allow-locked`, and compare with
`supportrl report`.

Serving an adapter with vLLM (Qwen3.5, thinking off):

```bash
vllm serve Qwen/Qwen3.5-9B --enable-lora --max-lora-rank 16 \
  --lora-modules support=runs/trl-9b/checkpoint-100 \
  --default-chat-template-kwargs '{"enable_thinking": false}'
supportrl eval examples/zoomberg --model support --base-url http://localhost:8000/v1 --split dev_val --name dv-100
```

Score a few episodes through transformers as well before trusting a new serving stack.
