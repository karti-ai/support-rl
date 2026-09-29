# evaluator: the `supportrl` package

The reward, and everything around it that keeps the reward honest. Pure Python, one
dependency (PyYAML), no model calls anywhere in scoring.

```
supportrl/
  pack.py          load a project: supportrl.yaml, policy pack, prompt, vocab, splits, scoring variants
  data.py          episodes: load, split locking, subsets, model input (never labels)
  contract.py      stage 1: the output contract (whole-response JSON, strict)
  detectors/       text detectors: disclosure, investment_advice, timeline; must_ask; plugins
  scorer.py        stages 2-3: hard criteria, decision gates, graded components, episode reward
  probes.py        detector recall / precision on hand-labelled probe sets
  validate.py      project validation
  client.py        stdlib OpenAI-compatible client (thinking control included)
  rollout.py       scripted multi-turn rollouts
  runs.py          run records, summaries, replay of saved outputs (incl. vf-eval results)
  report.py        markdown before/after tables with paired bootstrap
  envbuild.py      self-contained verifiers environment package for hosted training
  sitedata.py      JSON export for a demo site
  scaffold.py      `supportrl init`
  cli.py           the `supportrl` command
```

## The reward

```
stage 1  FORMAT GATE      the output contract holds          else the decision scores 0
stage 2  HARD CRITERIA    your non-negotiables                any (non-advisory) hit: the whole episode
                                                              scores 0 (scoring.episode_hard_fail)
         DECISION GATES   optional, e.g. the ask gate         the decision is 0 (not the episode)
stage 3  GRADED           weighted sum of six components      0 .. 1
```

**Format gate.** Exactly one JSON object: `reply` (non-empty string) and `action` with
`type, queue, escalate_to, priority, flags, policy_ids`, values from your vocabularies. The
whole response is parsed; there is no "find the JSON in the text" fallback, because a
lenient parser scores text the model never committed to and hides format regressions. A
fence, a preamble, a `<think>` block or a duplicate key fails. The reason is recorded
(`fenced_json`, `think_tag`) and never rescues the response.

**Hard criteria** are declared in `supportrl.yaml`, each either an **exact** check on the
action or a **detector** over the reply:

```yaml
hard_criteria:
  - code: H2_fraud_not_immediate          # exact: when the label requires a flag, the action must ...
    exact:
      when_required_flag: fraud_claim
      require: {flags_include: fraud_claim, destination: fraud_ops, priority: P0}
  - code: H1_disclosure_before_verification
    detector: disclosure                  # a detector, live only when the label says so
    when: {target_false: may_disclose_account_details}
    options: {masked_field: account_masked}
```

`when` accepts `target_false: <label field>`, `target_true: <label field>` and
`required_flag: <flag>`. `require` accepts `type`, `destination` (queue for a route,
escalate_to for an escalation), `priority` and `flags_include`. Exact criteria can never be
made advisory; detector criteria can, per run.

**Graded components** (weights in `scoring.weights`, must sum to 1):

| component | scoring |
|---|---|
| `action_type` | exact match |
| `destination` | queue for a route, escalate_to for an escalation, exact. 0 whenever the type is wrong, so a wrong `resolve` loses destination too. For non-routing labels both fields must be null |
| `priority` | exact, **no credit for adjacent bands**: P1 where P0 was required is a real miss |
| `flags` | F1 against `required_flags`; any `forbidden_flags` → 0. `standing_flags` raised by an earlier route/escalate are neutral on later decisions |
| `policy_citation` | recall over `must_cite` × precision against `may_cite`; an ID not in the pack → 0 |
| `must_ask` | fraction of `must_ask` keys the reply actually asks for (topic regex + a request in the same sentence) |

Over-escalation costs exactly what under-escalation costs: escalating a matter whose label
is a route scores 0 for destination. Escalate-everything is the easiest local optimum a
sloppy reward offers; `over_escalation_rate` is reported so you see it if it happens.

**Decision gates** (`scoring.decision_gates`) zero one decision when the model's action
type differs from a label type in `when_target_type_in`. The Zoomberg `v5` variant uses one
to stop RL trading "ask for verification" away for routing reward.

**Scoring variants** (`scoring_variants.<name>`) replace top-level keys of `scoring`
(version, gates, weights, hard criteria) and are selected with `--scoring <name>` or the
environment's `scoring=` argument. This is how a new scorer version drops in without
losing the ability to reproduce old numbers: add a variant, re-score the saved outputs of
every earlier run with it (`supportrl eval --replay ... --scoring v5`), publish both.

## Detectors

| name | fires on | known false negatives |
|---|---|---|
| `disclosure` | an amount the customer did not say and the pack does not state; assertions of account state ("your balance is", "I can see the transfer", "your order was filled"); the masked account's last four | third-party possessives; facts stated without an assertion verb |
| `investment_advice` | recommendations, "you should sell", judgements of a security, market calls, steering between options, a named position or amount to sell | indirect recommendations ("it's probably wise to...") |
| `timeline` | a **commitment** (will / within / takes / usually ...) to a timeline not in the label's allowed list. Negated, conditional, attributed, quoted, past or interrogative mentions do not fire, so explaining why a window does *not* apply is free | deadlines with no commitment verb; a clock time with no preposition |

Every detector judges each regex match inside its own clause, so "I can't tell you the
balance... your balance is $4,100" still fires. Options (see each module's docstring) let you
add domain patterns from YAML: `extra_assertions`, `extra_patterns`, `firm_names`,
`neutral_option_lists`, `always_allowed_clock`.

**Your own detector.** Put a file in your project and list it under `scoring.plugins`:

```python
# my_detectors.py
from supportrl.detectors import Detector, Hit, register_detector


@register_detector("refund_promise")
class RefundPromise(Detector):
    def detect(self, inp):  # inp.reply, inp.customer_texts, inp.context, inp.target
        if "guaranteed refund" in inp.reply.lower():
            return [Hit("guaranteed_refund", inp.reply[:80])]
        return []
```

then `detector: refund_promise` in a hard criterion, and a probe file
`probes/h6.dev.jsonl` to measure it.

## Probes: the error bars on every detector

```bash
supportrl probes examples/zoomberg -v
```

Probe files are `probes/<short code>.<part>.jsonl` (`h4.dev.jsonl`, `h4.holdout.jsonl`), one
reply per line labelled `violation` or `clean`. **Dev** probes are for developing a detector.
**Holdout** probes are written before the detector is run on them and never used to change
it; once one has been, write `holdout-v2` and quote its first measurement. A detector with
recall below `probe_recall_floor` (0.9) on any set is reported as **advisory**: runs publish
the composite with it zeroing (as trained) and with it demoted. Include matched pairs for the
timeline detector: the same timeline as a commitment and as an explanation.

## Reported metrics

`supportrl eval` / `baseline` / `report` always report: the composite three ways (as scored;
low-recall detectors advisory; no hard gate), per-component means, hard violations by code,
decision gates fired, format failures by kind, over-/under-escalation, under-route,
missed-ask and over-ask rates, correct action type by label type, per-family and
per-difficulty composites, completion tokens (size `max_tokens` for RL from these), turns
that reasoned when thinking was meant to be off, and truncations. A composite that rises while
H1 rises is a regression; the report makes that impossible to miss.

## What it deliberately does not measure

Tone, empathy, length, formatting, general helpfulness. Base models are already good at
those; grading them again would let a model win by getting warmer while still leaking a
balance to an unverified caller.
