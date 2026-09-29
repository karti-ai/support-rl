# recipe: from your support policy to a trainable project

This is the part that decides whether the numbers mean anything. The code is the easy half.
Budget most of your afternoon here.

```
1. policy pack      your support policy, rewritten as numbered, decidable rules      policies.md
2. action vocab     the actions an agent can take, and their fields                   supportrl.yaml: vocab
3. episode schema   what the model sees, what the label says                          supportrl.yaml: episodes
4. reward           which failures zero the conversation; weights for the rest         supportrl.yaml: scoring
5. validator rules  what the pack states unconditionally, checked on every label       supportrl.yaml: label_rules
6. data             ~100 conversations in disjoint slices; train / dev / test            data/
7. probes           hand-labelled replies for each detector                           probes/
```

Start with `supportrl init my-support`: it writes a small, complete project (a fictional
parcel carrier) that validates and scores. Replace it one file at a time and run
`supportrl validate my-support` after each change. Its `supportrl.yaml`
([source](../evaluator/supportrl/templates/project/supportrl.yaml)) is the annotated
reference for every config key; `examples/zoomberg/supportrl.yaml` is a full real one.

Templates to copy, in [`templates/`](templates/): `policy-pack.md`, `episode.json` (one
annotated conversation), `probes.jsonl`, `authoring-brief.md` (hand one to each author) and
`review-checklist.md` (for the cross-slice audit).

## 1. The policy pack

Take your real support policy (the help-centre macros, the escalation matrix, the thing new
agents are trained on) and rewrite it as a pack of **numbered, decidable rules**.
Template: [`templates/policy-pack.md`](templates/policy-pack.md).

- **One rule, one ID** (`IDV-01`, `FRD-03`). The model cites IDs; the scorer checks them. The
  `policy_id_pattern` in `supportrl.yaml` is how IDs are found in the file.
- **State every rule as a decision procedure.** "Escalate serious complaints" is not a rule.
  "A mention of a lawyer, a lawsuit or a regulator escalates to `legal` at P1; anger alone
  does not" is. A rule that says what the usual case is but not what makes an exception will
  be labelled two ways by two authors (the worked example's review log, entry 19).
- **Write the gates and their carve-outs together.** "Verify before disclosing" needs
  "verification gates disclosure, never protection" next to it, or a fraud report from an
  unverified caller has no correct answer.
- **Rank competing rules.** When two escalation triggers fire at once, which destination
  wins? Write it down before an episode needs it.
- **Name every number and every timeline the agent may state.** Anything the pack does not
  state, the agent does not know. This is what makes "invented timeline" checkable.
- **Say what the agent must not do**: advice, guarantees, speculating about causes, repeating
  full account numbers.

## 2. The action vocabulary

Every agent turn produces `{reply, action}` with the fixed contract
`type, queue, escalate_to, priority, flags, policy_ids`. You choose the values:

| field | you define | guidance |
|---|---|---|
| `type` | `action_types` (must include `route` and `escalate`; usually `resolve` and one or two `ask_*`) | define each type in `prompt.md`. Draw `resolve` narrowly: "no queue action is warranted now", not "I answered" |
| `queue` / `escalate_to` | `queues` | the real queues a human picks from. Fewer is better |
| `priority` | `priorities`, highest first | define each band operationally ("P0: funds at active risk"), because the scorer gives no credit for adjacent bands |
| `flags` | `flags` | define every flag, with a **"not set when"** column. Undefined flags are how two authors produce contradictory labels for the same situation |
| `standing_flags` | subset of flags | flags that belong to the ticket once it is routed, neutral on later turns |
| `must_ask` | key → topic regex | facts the reply must ask for (identity, order id). Satisfied by a sentence that matches the topic and makes a request |

Put the definitions in `prompt.md` too: the model has to know them.

## 3. The episode schema

One JSONL row per conversation ([`templates/episode.json`](templates/episode.json)):

- **model input**: `context` (session facts: verified or not, masked account, local time...;
  schema in `episodes.context`, rendered by `prompt.context_template`) and `turns` (customer
  turns with text; agent turns as empty decision points `d1..dN`, at most `max_decisions`)
- **answer key**: `family`, `difficulty` (`standard` / `hard` / `trap`), and one label per
  decision point: action fields, `required_flags` / `forbidden_flags`,
  `must_cite` / `may_cite`, `must_ask`, the gate fields your hard
  criteria key on (e.g. `may_disclose_account_details`), `allowed_timeline_claims`, and a
  `rationale` that cites policy. The rationale is for humans; it is never scored or shown.

Customer follow-ups are **scripted**: written once, replayed whatever the model says. That
keeps rewards comparable and eval reproducible. Write each follow-up as the customer's
plausible next message after a *reasonable* agent turn, and never make it depend on one
particular reply.

**Follow-up turns.** One conversation is one ticket. Once a decision routes or escalates,
a later decision routes or escalates again only if the new turn **outranks** the standing
disposition (any escalation > any route, then priority). Everything else (pressure,
restated threats, advice bait, a lower-priority side issue) is `resolve`. The validator
enforces this (`follow_up_rule`).

## 4. The reward

Pick the handful of failures that must zero a conversation no matter what else was right.
Prefer **exact** criteria (flag X required ⇒ action must reach Y at priority Z): they cannot be
fooled. Use a **detector** only where the failure lives in free text (disclosure, advice, an
invented timeline), and measure it with probes before you trust it. Then set the component
weights **before any model is run**. See [`../evaluator/README.md`](../evaluator/README.md).

Guard the two easy local optima:
- **escalate everything**: over-escalation must cost what under-escalation costs (the
  `destination` component does this) and `over_escalation_rate` must be reported;
- **answer everything in chat**: a wrong `resolve` must lose destination as well as type
  (it does), and `under_route_rate` must be reported. If you have ask actions, consider a
  decision gate so RL cannot trade asking away (the worked example's v5).

## 5. Label rules

Rules the pack states unconditionally become `label_rules` in `supportrl.yaml`, and every
label is checked against them (`when_required_flag` / `from_required_flag` / `when_true`,
then `require` action type, destination, priority, timeline or citation inclusions). This is
how a rule change reaches every existing label instead of the next author only.

## 6. Data, splits, authoring

About 100 conversations is enough for a first model: the worked example used 56 train, 18
dev and 32 test. Make test **harder** than train and cover every family in it. Fix the dev
partition (`dev_val` for checkpoint selection, `dev_holdout` reported only) **before any model
output on dev is seen**, and lock test. How to write them without drifting apart:
[`AUTHORING.md`](AUTHORING.md).

## 7. Probes

For each detector: a dev probe set (grows with every fix) and a holdout set written before
the detector runs on it, half violations and half clean, with matched pairs for anything
that has a "reference, not commitment" exemption. Templates:
[`templates/probes.jsonl`](templates/probes.jsonl). Run `supportrl probes`; a detector under
0.9 recall is reported as advisory.

## Checklist before you train

- [ ] `supportrl validate` passes; every warning read
- [ ] `supportrl probes` run; advisory detectors noted
- [ ] cross-slice audit done ([`templates/review-checklist.md`](templates/review-checklist.md))
- [ ] weights, hard criteria and selection rule committed before any model output was seen
- [ ] frozen baseline on dev for your base model(s), thinking off verified in `summary.json`
- [ ] test split untouched
