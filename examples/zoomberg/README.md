# Worked example: Zoomberg Brokerage

A multi-turn support desk for **Zoomberg Brokerage**, a fictional US retail brokerage. At
each agent turn the model writes the customer's reply **and** a triage action: route or
escalate, which queue, what priority, which flags, which policies. It is the project that
produced [Karti-Small-Support-9B](https://huggingface.co/KartiOS/Karti-Small-Support-9B), and
everything needed to check that model's numbers is here.

```
supportrl.yaml     the whole scoring config: vocab, weights, hard criteria, label rules, splits
policies.md        policy pack v1.4 (63 policies, 14 categories) -- appended to the prompt
prompt.md          model-facing instructions: output contract, action and flag semantics
data/              train.jsonl (56 episodes / 77 decisions), validation.jsonl (18 / 26), test.jsonl (32 / 53)
probes/            hand-labelled detector probes: dev, holdout, holdout-v2
results/           frozen model outputs: test/, dev/ and the three dev_val selection candidates
configs/           the hosted RL config that trained v1
docs/              SCHEMA, EVALUATOR, GOLD-EXAMPLES, REVIEW-LOG (as published with the dataset)
scripts/           fetch_from_hf.py: verify / refresh the vendored data against the Hub
```

`validation` is the project's `dev` split and `test` its locked `test` split; `dev` is
partitioned into `dev_val` (9 episodes, checkpoint selection) and `dev_holdout` (9, reported,
never used to select). In `docs/SCHEMA.md` the same files appear under their original names
(`dev`, `eval`, tickets/targets); `data/*.jsonl` is the joined one-row-per-episode form.

**Why the data is vendored, not downloaded:** the quickstart, `eval --replay` and the tests
must run offline with no account; the data is about 300 KB; and the frozen results must be
scored against exactly the data they came from. `scripts/fetch_from_hf.py --check` proves
`data/` and `policies.md` are byte-identical to the Hub release (revision `6469529a`), and
pulls a newer release when one adds episodes. `docs/` started as the dataset's docs and
carries small wording edits (listed in DATA-LICENSE.md).

## Reproduce the published numbers (offline, no cost)

```bash
supportrl validate examples/zoomberg        # 0 errors; 7 warnings = the intended full-number traps
supportrl probes examples/zoomberg          # H1 holdout 0.88, H4 0.62, H5 1.00 recall; precision 1.00
supportrl report examples/zoomberg \
    examples/zoomberg/results/test/qwen3.5-4b-base \
    examples/zoomberg/results/test/qwen3.5-9b-base \
    examples/zoomberg/results/test/support-9b-v1 \
    --labels "Qwen3.5-4B base" "Qwen3.5-9B base" "v1"
supportrl train examples/zoomberg --backend select --candidates \
    step7=examples/zoomberg/results/dev_val/v1-candidate-step07 \
    step14=examples/zoomberg/results/dev_val/v1-candidate-step14 \
    step21=examples/zoomberg/results/dev_val/v1-candidate-step21
```

`tests/test_zoomberg_regression.py` asserts every one of these numbers.

### Frozen results (scoring `fst-scorer-v4`)

| split | run | composite | H1/H4 advisory | no hard gate | hard-failed |
|---|---|---|---|---|---|
| test | Qwen3.5-4B base | 0.502 | 0.552 | 0.562 | 3 / 32 |
| test | Qwen3.5-9B base | 0.531 | 0.569 | 0.638 | 6 / 32 |
| test | **v1 (step 14)** | **0.706** | 0.738 | 0.738 | 1 / 32 |
| dev | Qwen3.5-4B base | 0.507 | | | |
| dev | Qwen3.5-9B base | 0.509 | | | |
| dev | v1 | 0.747 (dev_val 0.775, dev_holdout 0.719) | | | |
| dev_val | candidates at steps 7 / 14 / 21 | 0.644 / **0.786** / 0.514 | | | |
| test | v2 (step 7, not released) | 0.606 (v5: 0.597) | 0.637 | 0.688 | 4 / 32 |
| dev | v2 | 0.600 (v5: 0.589) | | | |
| dev_val | v2 candidates at steps 7 / 14 / 21 (v5) | **0.664** / 0.475 / 0.594 | | | |
| test | v3 (step 24, not released) | 0.695 (v5: 0.664) | 0.726 | 0.726 | 1 / 32 |
| dev | v3 | 0.718 (v5: 0.704; dev_val_v2 0.692, dev_holdout_v2 0.717) | | | |
| dev_val_v2 | v3 candidates at steps 16 / 20 / 24 / 28, mean of 3 passes (v5) | 0.684 / 0.675 / **0.692** / 0.571 | | | |

All runs: T=0, thinking off (`chat_template_kwargs.enable_thinking=false`), 1024 max tokens,
one rollout, hosted OpenAI-compatible serving. Hosted adapter serving at T=0 is not
bit-deterministic: the same step-14 adapter read 0.786 and then 0.775 on dev_val.

**What changed and what did not.** v1 learned to resolve and route far better and stopped
over-escalating (0.302 / 0.170 → 0.000). It also asks for identity verification less often
(ask_verification correct 2/7 against the 9B base's 5/7), and resolves slightly more matters
that should be routed (under-route 0.038 → 0.094). Paired bootstrap on test: v1 − 9B base
= +0.175 [+0.055, +0.298]. The one remaining hard failure (EVAL-0600, H1) is a detector false
positive: stating the general funding rule to a caller who asked for the rule. A by-eye read
of all 53 v1 test replies found no missed advice, no missed timeline, one missed disclosure
(EVAL-0605 d2), and one arithmetic error no detector could see (EVAL-0300 d1: a 30-minute
window called closed after 24 minutes).

### v2: a documented negative result

v2 was trained to fix v1's verification regression, with scoring v5 (below) and 15 extra
train-only episodes (TST-TRAIN-0700..0714) that are not in the dataset revision vendored
here. Dev and test are unchanged, so its outputs are scored here like every other run. It
recovered the asks (ask_verification 5/7) and lost most of v1's routing (resolve 9/19, route
9/19, over-escalation 0.170), for a test composite of 0.606 (v4) / 0.597 (v5). It failed the
ship rule written before training (v4 composite ≥ 0.69 and asks ≥ 5/7), so it was not
released and v1 stays the model. Two reasons stand out, both from train and dev evidence:
`dev_val` has no ask targets, so selection could not see the fix and chose step 7 on routing
noise; and the harsher reward and harder new episodes slowed routing learning within 21
steps.

```bash
supportrl report examples/zoomberg examples/zoomberg/results/test/support-9b-v1 \
    examples/zoomberg/results/test/support-9b-v2 --labels v1 v2
```

### v3: warm start from v1, better selection, still no asks

v3 continued from v1's checkpoint for 14 steps at half the learning rate, under scoring v5
and v2's train data, and fixed the two selection flaws v2 exposed:

- **`dev_val_v2` / `dev_holdout_v2`** (in `supportrl.yaml`): a mechanical re-cut of dev, fixed
  before any v3 output, so the selection half contains one ask_verification and one
  ask_clarifying target. The v1 split names are unchanged, so earlier runs stay reproducible.
- **Three T=0 passes per candidate**, averaged. The same adapter can move ~0.08 between passes
  on 9 episodes (`results/dev_val_v2/*-p{1,2,3}` show it).
- **An ask guard**: a candidate whose pooled ask accuracy on `dev_val_v2` is below the 9B
  base's (2/6) is rejected; if all fail, the best composite is still evaluated once and the
  failure reported.

Every candidate asked 0/6 and failed the guard, which predicted the test result before it
was run. Step 24 (mean 0.692) was evaluated once: composite **0.695** (v5 0.664), asks 2/7,
resolve 13/19, route 13/19, over-escalation 0.038; v3 − v1 = −0.011 [−0.060, +0.046]. It failed
the ship rule on asks, and v1 stays the released model. Reproduce the selection:

```bash
R=examples/zoomberg/results/dev_val_v2
p() { echo $R/$1-p1,$R/$1-p2,$R/$1-p3; }
supportrl train examples/zoomberg --backend select --scoring v5 --subset dev_val_v2 \
    --ask-guard $(p qwen3.5-9b-base) \
    --candidates step16=$(p v3-candidate-step16) step20=$(p v3-candidate-step20) \
                 step24=$(p v3-candidate-step24) step28=$(p v3-candidate-step28)
```

### The v5 variant: closing the verification regression

`supportrl.yaml` also defines `scoring_variants.v5`, which adds an **ask gate**: on a
decision whose target is an ask action, any other action type scores that decision 0 (not
the episode). Under v4, a `resolve` on an `ask_verification` target kept up to 0.60 of the
decision, so the reward paid more to stop asking than to keep asking. Re-scoring the same
saved outputs, with no model calls:

```bash
supportrl eval examples/zoomberg --replay examples/zoomberg/results/test/support-9b-v1 --scoring v5
```

gives 4B 0.481, 9B 0.526, v1 0.666 (and v2 0.597, v3 0.664, both trained under it). The default stays v4 because it reproduces the v1
numbers. To train against v5, pass `scoring = "v5"` in the environment args (the verifiers
environment takes `scoring=`), or set the variant as the default in a copy of this project.

## Regenerate the results (needs an endpoint, costs money)

Baselines, with any OpenAI-compatible server. The published ones used Prime Inference:

```bash
export PRIME_API_KEY=...          # read from the environment, never written to run records
supportrl baseline examples/zoomberg --model Qwen/Qwen3.5-9B \
    --base-url https://api.pinference.ai/api/v1 --api-key-env PRIME_API_KEY --split dev
# the frozen before-number on test, once per model:
supportrl eval examples/zoomberg --model Qwen/Qwen3.5-9B \
    --base-url https://api.pinference.ai/api/v1 --api-key-env PRIME_API_KEY --split test --allow-locked
```

The published baselines were produced with `vf-eval` from verifiers 0.2.0 driving the
same environment; `supportrl baseline` sends the same messages and the same sampling fields
(it uses `max_tokens` where vf-eval sends `max_completion_tokens`). Cost at list price was
about $0.02–0.06 per split per model.

Training, on Prime Intellect's hosted RL:

```bash
supportrl train examples/zoomberg --backend prime --model Qwen/Qwen3.5-9B --owner <hub-user>
# review runs/train/zoomberg-qwen3.5-9b-lora/prime-rl.toml, then:
supportrl train examples/zoomberg --backend prime --model Qwen/Qwen3.5-9B --owner <hub-user> --launch
```

`configs/prime-rl-v1.toml` is the exact config v1 ran with (rendered defaults match it except
`shuffle_seed`). Then deploy each saved adapter, score it on `dev_val` with
`supportrl eval ... --split dev_val`, apply the selection rule with
`supportrl train ... --backend select --candidates ...`, and run the selected adapter on
test **once** with `--allow-locked`. v1: $5.45 of training, about $0.14 of evaluation.

Or on your own GPU, with TRL: see [`train/README.md`](../../train/README.md).

## Limits

- Small: 106 episodes. One decision moves the test composite by about 0.02.
- One fictional firm and one pack. The model learns *this* pack in context.
- The pattern-day-trader rules (RST-01/RST-02) model the framework as it stood before FINRA's
  2026 Rule 4210 amendments. The pack is fictional house policy, not current regulation.
- H1 and H4 are text detectors with holdout recall below 0.9; they are reported as advisory
  alongside the main composite. The advice detector misses indirect recommendations; the
  timeline detector cannot tell CMP-04's acknowledgement window from an invented resolution
  time of the same length. See `docs/EVALUATOR.md`.
- Tax advice (TAX-03) and the `guarantee`, `merits_argument`, `cause_speculation`, `probing`
  and `full_account_number` classes are labelled but not scored.

Data license: CC-BY-4.0, attribution Karti Tripathi — KartiOS/fintech-support-triage. Not
covered by the repository's Apache-2.0 license. Details: [DATA-LICENSE.md](DATA-LICENSE.md).
