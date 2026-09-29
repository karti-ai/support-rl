# support-rl

**Train your own support-triage model in an afternoon, for under $10, with no judge model.**

support-rl is for a small engineering team that wants a support chat model that follows
*its own* written policy: verify before disclosing, route fraud at P0, escalate a lawyer
mention, never invent a timeline. You write the policy pack and about a hundred labelled
conversations. support-rl turns them into an RL environment whose reward is **computed in
code**, measures your base model, trains a LoRA adapter (on a hosted RL service or on one GPU
of your own), picks the checkpoint by a rule you fixed in advance, and reports the before and
after honestly.

```
customer turn ─▶ [ your policy pack in the prompt ] ─▶ { reply, action }
                                                          action = type, queue | escalate_to,
                                                                   priority, flags, policy_ids
reward = format gate ─▶ hard criteria (zero the episode) ─▶ weighted components   ← all code
```

Why code and not an LLM judge? A judge has to be built, audited across model families and
paid for on every rollout, and RL is very good at finding whatever it likes that you did
not mean. Most of what matters in support triage is checkable: which queue, what priority,
which policy, whether a gate was respected. support-rl scores exactly that, and puts the
fuzzy parts (did the reply disclose an account fact? promise a timeline?) behind text
detectors whose recall and precision you measure on hand-labelled probes and publish with
every number.

## Case study: Karti-Small-Support-9B

The worked example ([`examples/zoomberg/`](examples/zoomberg/)) is a fictional US brokerage
with a 63-policy pack and 106 multi-turn conversations. A LoRA adapter on Qwen3.5-9B was
trained with hosted RL for **$5.45** of training (plus about $0.14 of evaluation), 14 steps,
selected on a validation half that never touched training.

Held-out test split, 32 conversations and 53 decisions, each model run once, T=0, thinking off:

| | Qwen3.5-4B base | Qwen3.5-9B base | **v1** |
|---|---|---|---|
| **Composite** (a hard violation zeroes the conversation) | 0.502 | 0.531 | **0.706** |
| Composite, H1/H4 advisory | 0.552 | 0.569 | 0.738 |
| Conversations hard-failed | 3 / 32 | 6 / 32 | **1 / 32** |
| Correct action: resolve / route | 4/19 · 7/19 | 7/19 · 8/19 | **17/19 · 13/19** |
| Over-escalation rate | 0.302 | 0.170 | **0.000** |
| Correct action: ask_verification | 3/7 | 5/7 | **2/7 ↓** |
| Under-route rate | 0.000 | 0.038 | 0.094 ↑ |

**+0.175 over its own base, paired bootstrap 95% CI [+0.055, +0.298]**; 19 conversations
better, 3 worse, 10 unchanged. Every number above is reproduced from the saved outputs by
`supportrl report` and locked by a test.

It is not a free win, and the repo says so:

- **v1 asks for identity verification less often** (2 of 7 against 5 of 7 for its base).
  Under the v1 reward a wrong `resolve` on an ask target still kept up to 0.60 of the
  decision, so RL traded asking away for the larger routing reward. The `v5` scoring variant
  in the example adds a gate that zeroes such a decision; re-scored under it, the same
  outputs read 0.481 / 0.526 / 0.666. Put a verification gate in front of any model you train.
- **Small data.** 56 training and 32 test conversations: one decision moves the composite by
  about 0.02. The composite gain clears the noise; most per-component differences do not.
- **The detectors are the ceiling on what is measured.** On their holdout probes the
  disclosure detector has 0.88 recall and the advice detector 0.62 (precision 1.00 on both),
  so those two are also reported as advisory. The one hard failure left in v1 is a detector
  false positive, and a by-eye read of all 53 v1 replies found one disclosure the detector
  missed.

### Results so far

- **v1** (above) is the released model.
- **v2 was a negative result, and it is recorded as one.** It tried to fix v1's
  verification regression: the v5 ask gate in the reward, plus 15 extra train-only episodes
  built around asking. It recovered the asks (ask_verification 5/7, as good as the base) but
  lost most of v1's routing (resolve 17/19 → 9/19, route 13/19 → 9/19, over-escalation back
  to 0.170). Test composite fell from 0.706 to **0.606** under the v4 scorer (0.597 under v5).
  v1 − v2 = +0.100, CI [+0.026, +0.188]. It failed the ship rule written before
  training (v4 composite ≥ 0.69 and asks ≥ 5/7), so it was not released. The likely reasons,
  from train and dev evidence only:
  - the `dev_val` half used for checkpoint selection contains no ask targets, so selection
    could not see the fix and picked the least-trained checkpoint (step 7) on routing noise;
  - the harsher reward and harder new data slowed routing learning within the same 21 steps.

  Its outputs are frozen in `examples/zoomberg/results/*/support-9b-v2` and in the site export.
- **v3 did not ship either.** It continued from v1 (warm start) under the same ask-gated
  reward, and fixed both process flaws from v2: a selection half that contains ask targets
  (`dev_val_v2`), three T=0 passes per candidate (hosted T=0 is not deterministic), and an
  ask guard (reject a candidate that asks less than the base). Every candidate asked 0/6 on the
  selection half and failed the guard *before* the test run; the best composite was run once
  anyway, as the rule required. Test: composite 0.695, asks still 2/7; v3 − v1 = −0.011
  [−0.060, +0.046], flat within noise. It failed the ship rule on asks.
- **v1 stays the released model.** Read across v2 and v3: starting from the base, the ask-gated
  reward restores asks but loses routing; starting from v1, a gentle continuation keeps routing
  but not asks. Neither found a checkpoint with both. The multi-pass, ask-guarded selection is
  available as `supportrl train --backend select --candidates name=RUN,RUN,RUN --ask-guard ...`
  (off by default).

Model: [KartiOS/Karti-Small-Support-9B](https://huggingface.co/KartiOS/Karti-Small-Support-9B) ·
Dataset: [KartiOS/fintech-support-triage](https://huggingface.co/datasets/KartiOS/fintech-support-triage) ·
Demo: [models.karti.ai/support](https://models.karti.ai/support) — replay every test episode, base vs trained, in the [explorer](https://models.karti.ai/support/explorer/).

## Quickstart

Everything below runs offline, with no API keys.

```bash
git clone https://github.com/karti-ai/support-rl && cd support-rl
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

supportrl validate examples/zoomberg          # schema, vocab, policy IDs, label rules, leakage
supportrl probes examples/zoomberg            # detector recall / precision on the probe sets
supportrl eval examples/zoomberg --replay examples/zoomberg/results/test/support-9b-v1
supportrl report examples/zoomberg \
    examples/zoomberg/results/test/qwen3.5-9b-base examples/zoomberg/results/test/support-9b-v1
```

Start your own project from the starter template (a small, complete project for a fictional
parcel carrier) and replace it piece by piece:

```bash
supportrl init my-support
supportrl validate my-support
```

With a model endpoint (vLLM, SGLang, Ollama, OpenAI, OpenRouter, Prime Inference, anything
OpenAI-compatible):

```bash
supportrl baseline my-support --model Qwen/Qwen3.5-4B --base-url http://localhost:8000/v1
supportrl train my-support --backend prime --model Qwen/Qwen3.5-4B --owner <hub-user>   # renders config; --launch to run
supportrl train my-support --backend trl --model Qwen/Qwen3.5-4B --output-dir runs/trl  # needs .[train] + a GPU
supportrl eval my-support --model <adapter> --base-url ... --split test --allow-locked  # once
supportrl report my-support runs/baseline-dev-... runs/eval-dev-...
```

`--api-key-env NAME` names the environment variable that holds a key; keys are never passed
on the command line or written to run records.

## How it fits together

| directory | what it is |
|---|---|
| [`recipe/`](recipe/) | how to turn your support policy into a policy pack, an episode schema and an action vocabulary, and how to author and review the data. Templates to copy |
| [`evaluator/`](evaluator/) | the `supportrl` package: output contract, scorer, detectors, probes, validator, runs, report, CLI. Weights, vocabularies and hard criteria come from your `supportrl.yaml` |
| [`simulator/`](simulator/) | scripted customer (deterministic replay, used for eval and training) and an LLM customer (generates new *unlabelled* candidate conversations and play-tests a model) |
| [`env/`](env/) | a [verifiers](https://github.com/PrimeIntellect-ai/verifiers) environment for any project, and a builder for a self-contained package a hosted trainer can install |
| [`train/`](train/) | hosted LoRA RL on Prime Intellect (config template + one command), self-hosted GRPO + LoRA with TRL on one GPU, and checkpoint selection |
| [`examples/zoomberg/`](examples/zoomberg/) | the full worked example: data, config, probes, frozen baselines, v1 results, and the exact commands |
| [`site-data/`](site-data/) | exports saved runs as JSON a demo site can replay |

The CLI: `supportrl init | validate | probes | baseline | eval | train | report | simulate | play | env build`.
`supportrl <command> -h` documents each.

## The method, in five rules

1. **Write the rules down first, then the data, then the scorer.** The policy pack is the
   ground truth. A label that cannot cite a policy is an opinion.
2. **Keep test locked.** It loads only with `--allow-locked`, is run once per model, and is
   never used to choose anything. Checkpoints are chosen on `dev_val` by a rule written in
   `supportrl.yaml` before training.
3. **Freeze a baseline before training.** Same prompt, same sampling, same scorer, same
   split. A result without a frozen before-state is not a result.
4. **Report the failure modes separately.** Hard violations by code, format failures,
   over-escalation, under-routing, missed asks. A composite that rises while one of those
   gets worse is a regression, and the report makes it visible.
5. **Measure your detectors.** Hand-labelled probes, holdout sets written before the
   detector is run on them, and the composite reported both ways when recall is below 0.9.

## Status and limits

- Tested: the evaluator, validator, CLI, report and site export (offline test suite in CI,
  including exact reproduction of every published Zoomberg number); the verifiers
  environment and the built environment package, against verifiers 0.2.0 with `vf-eval` and
  a mock endpoint; the hosted-RL config rendering. v1 was trained on the hosted path with the
  single-project environment this package generalises. A package built by
  `supportrl env build` has not itself run a hosted training job yet.
- **Not yet run end to end in this repo:** the TRL backend on a GPU and local checkpoint
  selection. The dataset construction and reward function are tested; the training loop is
  written against TRL's documented GRPO API but has not been run here. Treat it as a starting
  point and report back.
- Text only, English only. The scripted customer never reacts to the model; the LLM customer
  is for generating candidates and play-testing, never for reward.

## License

Code: Apache-2.0 ([LICENSE](LICENSE)).

The Zoomberg example data, policy pack, docs, probes and model outputs
(`examples/zoomberg/`, and the exports in `site-data/out/`) are **not** covered by the
Apache-2.0 license. They are licensed
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/), attribution: Karti Tripathi —
[KartiOS/fintech-support-triage](https://huggingface.co/datasets/KartiOS/fintech-support-triage).
The exact file list and source revision are in
[`examples/zoomberg/DATA-LICENSE.md`](examples/zoomberg/DATA-LICENSE.md).

Zoomberg Brokerage is fictional. Nothing here is legal, regulatory, tax or financial advice,
and a model trained with it drafts a reply and proposes an action for a human to review.
