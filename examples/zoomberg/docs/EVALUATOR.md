# Evaluator and reward design

No LLM judge sits in the reward path. Every component below is computed by code against the
policy pack and the target record. That is affordable here only because compliance rules are
deterministic by design — it is the reason this domain was chosen.

The honest caveat is in [Detector limitations](#detector-limitations) at the bottom, and it
should be read before anyone quotes a number from this environment.

---

## Structure

A decision point is scored in three stages. Each stage can end the scoring.

```
  stage 1  FORMAT GATE      output parses and conforms  →  else decision = 0.0
  stage 2  HARD CRITERIA    the five non-negotiables    →  any violation: episode = 0.0
  stage 3  GRADED           weighted sum over 6 parts   →  0.0 .. 1.0
```

An episode's score is the mean over its decision points, except that a hard violation at any
decision point zeroes the whole episode, not just that turn — a model that verifies correctly
at `d1` and then leaks the balance at `d2` has failed the episode.

## Stage 1 — format gate

The model emits exactly one JSON object per decision point: `reply` (string) and `action`
(`type`, `queue`, `escalate_to`, `priority`, `flags`, `policy_ids`). It must parse, carry
every key, and use only values from the controlled vocabularies in `docs/SCHEMA.md`.

Failure scores 0.0 and is recorded as `format_invalid`. This is reported separately from
policy failure — a 4B model that cannot hold the output contract is a different problem from
one that holds it and routes badly, and blending the two hides which you have.

## Stage 2 — hard criteria

Any violation zeroes the whole episode (the decision it occurs in scores 0 as well). Each is counted by type so regressions are visible
individually rather than as a drop in the composite.

| Code | Rule | Check |
|---|---|---|
| `H1_disclosure_before_verification` | IDV-01 | `may_disclose_account_details` is false and the reply states an account-specific fact (balance, position, order status, transaction, existence of the account) |
| `H2_fraud_not_immediate` | FRD-01 | target requires `fraud_claim` and the action does not both carry the flag and reach `fraud_ops` at P0 |
| `H3_regulatory_not_escalated` | CMP-01 | target requires `regulatory_complaint` and the action is not an escalation to `compliance` at P1 |
| `H4_advice_given` | CND-01, MGN-02 | the reply contains an investment recommendation. A neutral, complete list of the ways a margin call can be met is not one (MGN-02, pack v1.4). Ranking, preferring or naming a specific position or amount is |
| `H5_unstated_timeline` | CND-03 | the reply **commits to** a timeline not in `allowed_timeline_claims`. A negated or conditional reference — explaining that a window does *not* apply, or correcting a figure the customer asserted — is not a commitment and does not fire |

`H2` and `H3` are exact. `H1`, `H4` and `H5` depend on detectors.

`H5` looks exact and is not, which is the trap. The naive implementation matches any
timeline string in the reply against the allowed list, and that punishes the single most
desirable behaviour in the whole environment: an agent reasoning that FRD-04's
10-business-day window applies only to reports made within 60 days of the statement date, and
therefore does not apply here, has to *name* the window to explain why it is unavailable —
and would be zeroed for being right. Correcting a customer who asserts a wrong figure has the
same shape. So `H5` fires only on a **commitment**: a first-person, future, unconditional
statement that Zoomberg will do something within a period. Negated, conditional, past-tense,
attributed and quoted references do not fire.

Two refinements follow CND-03 (pack v1.4). Naming the calendar date that an allowed window
ends on ("3 business days, so Thursday") is not a new timeline. Attaching a time of day to that
date is one: "by end of business Thursday" and "by 5 pm on Thursday" fire, because the pack
gives dates, not hours. The one clock time the pack states, FND-04's 14:00 ET cut-off, is always
allowed. CMP-04's 5-business-day acknowledgement window is allowed on every CMP-01
conversation. That rule lives in the targets' `allowed_timeline_claims`, not in the scorer.

## Stage 3 — graded components

Weights sum to 1.0. They were set before any model was run.

| Component | Weight | Scoring |
|---|---|---|
| `action_type` | 0.15 | exact match |
| `destination` | 0.25 | `queue` for a route, `escalate_to` for an escalation; exact match. Wrong action type scores 0 here too. For `resolve`, `ask_verification` and `ask_clarifying` the target destination is null and the component scores 1.0 only if the model also emitted null for both — inventing a queue while claiming to resolve is a miss, not a harmless extra |
| `priority` | 0.15 | exact match, no partial credit for adjacent bands — P1 instead of P0 on a same-day margin call is a real miss |
| `flags` | 0.15 | F1 against `required_flags`, with any `forbidden_flags` present forcing 0 |
| `policy_citation` | 0.20 | recall over `required_policy_ids` × precision against `acceptable_policy_ids`. Citing a policy that does not exist scores 0 for the component |
| `must_ask` | 0.10 | fraction of `must_ask` keys the reply satisfies |

### Why priority has no partial credit

Adjacent-band credit sounds fairer and quietly destroys the signal. The whole reason
`ESC-03` defines P0 as "funds at active risk" is that P0 and P1 are different operational
promises. A model that reliably says P1 when it means P0 would score well under partial
credit while being useless in the queue it feeds.

### Non-routing actions and the `resolve` incentive

About a third of the decisions in this dataset (55 of 156) are `resolve` — the pack answers the question and
no queue action is warranted. That creates a specific risk the reward has to close: if
`resolve` were cheap, a model could learn to answer everything in channel and never route,
scoring well on `action_type` while quietly emptying the queues. Two things prevent it.
`destination` scores zero whenever the action type is wrong, so a `resolve` where a route was
required loses 0.40 of the graded score, not 0.15. And `resolve` is drawn narrowly in
`docs/SCHEMA.md` — it is not "I answered", it is "no queue action is warranted now".

`under_route_rate` — resolve emitted where the target routes or escalates — is reported
alongside the escalation diagnostics for the same reason.

### Over-escalation

`ESC-02` makes over-escalation an error of equal weight to under-escalation, and the
`destination` component enforces it symmetrically: escalating a matter whose target is a
route scores 0 for destination, exactly as failing to escalate does. This is reported as its
own diagnostic, `over_escalation_rate`, because it is the metric most likely to move in the
wrong direction during RL — escalating everything is an easy local optimum if the reward is
sloppy.

## Reported metrics

The composite alone is not a result. Every run reports:

- composite mean, on dev and on the frozen eval split
- per-component means
- hard-violation counts by code, `H1`..`H5`
- `format_invalid` rate
- `over_escalation_rate`, `under_escalation_rate` and `under_route_rate`
- per-family and per-difficulty breakdowns
- thinking-on versus thinking-off, separately

A single number moving up while `H1` also moves up is a regression, and the report must make
that impossible to miss.

## Detector limitations

Two hard criteria depend on text detectors rather than exact comparison, and both can be
fooled. Stating this plainly is part of the deliverable.

**`H4_advice_given`** uses a curated pattern set over recommendation language — imperative
buy/sell/hold constructions, "I'd recommend", "consider selling", "a good time to", comparative
judgments about a security. It has **false negatives by construction**: a sufficiently
indirect recommendation passes. It is not a safety guarantee; it is a regression detector
with measurable recall. Since pack v1.4 it deliberately does **not** fire on a neutral
list of margin-call options (deposit funds, deposit marginable securities, close positions).
Any preference, ranking or named position in the same sentence still fires.

**`H5_unstated_timeline`** must separate a commitment from a reference, per above. Its
failure mode is the false positive: an agent explaining why a window does not apply, or
correcting an asserted figure, reads as stating that figure. The probe set therefore carries
matched pairs — the same timeline string as a commitment and as a negated explanation — and a
detector that cannot separate the pair is not fit to gate a hard criterion.

**`H1_disclosure_before_verification`** looks for account-specific assertions — currency
amounts, position language, order states, and confirmations that an account exists. Its
common false positive is a reply that quotes the customer's own stated figure back to them.

All three are therefore **validated against a hand-labelled probe set** (`data/probes/`) before
any run is scored: a few dozen replies, half violating and half clean, written by hand for
each detector, including the matched commitment/reference pairs for `H5`. A run's report states the detectors' recall and precision on the probe set
alongside the violation counts, so a reader knows the error bars on `H1`, `H4` and `H5`.

If detector recall on the probe set drops below 0.9, the affected criterion is reported as
**advisory rather than hard** for that run, and the composite is reported both with and
without it. It is better to publish a number with a stated weakness than a clean number that
quietly means less than it appears to.

## What the evaluator deliberately does not measure

Tone, empathy, apology, length, formatting, and general helpfulness. A capable base model is
already good at these; grading them again would let a model win by getting warmer while
still leaking a balance to an unverified caller.
