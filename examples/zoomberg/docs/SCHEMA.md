# Data schema — fintech support triage

> **Paths in this release.** This schema describes the two-file layout. In this repository it
> lives in `raw/`: `raw/{train,dev,eval}.tickets.jsonl` and `raw/{train,dev,eval}.targets.jsonl`.
> Where the text below says `data/<split>.tickets.jsonl` or `data/<split>.targets.jsonl`, read
> `raw/`. `data/{train,validation,test}.jsonl` holds the same episodes with ticket and target
> joined into one row (dev → validation, eval → test), with `decisions` as a list. The policy
> pack is `policies/policies.md`. `env/scripts/validate_dataset.py` is not part of this
> release.

Two files per split, joined by `id`. **Tickets are model input. Targets are never model
input** — not the action, not the rationale, not the family, not the difficulty.

```
data/train.tickets.jsonl   data/train.targets.jsonl
data/dev.tickets.jsonl     data/dev.targets.jsonl
data/eval.tickets.jsonl    data/eval.targets.jsonl
```

## ID format

`TST-<SPLIT>-<NNNN>` — `TST-TRAIN-0001`, `TST-DEV-0001`, `TST-EVAL-0001`. Unique across all
splits.

## Ticket record

```json
{
  "id": "TST-TRAIN-0001",
  "context": {
    "verified": false,
    "account_masked": "****4471",
    "account_type": "margin",
    "account_age_days": 412,
    "local_time_et": "2026-03-11T10:42:00-04:00"
  },
  "turns": [
    {"t": 0, "role": "customer", "text": "..."},
    {"t": 1, "role": "agent", "decision_point": "d1"},
    {"t": 2, "role": "customer", "text": "..."},
    {"t": 3, "role": "agent", "decision_point": "d2"}
  ]
}
```

- `verified` — whether identity verification has already succeeded when the episode opens.
- `account_type` — `margin` or `cash`.
- `local_time_et` — matters for FND-04 (14:00 wire cut-off) and TRD-04 (30-minute window).
- `turns` alternate customer/agent. Agent turns carry a `decision_point` id and no text —
  the model produces both the reply and the action there.
- 1–3 decision points per episode. Customer turns after a decision point are **scripted**:
  they are written as the customer's plausible next message and do not depend on what the
  model said. That is what keeps rollouts deterministic and eval reproducible.

## Target record

```json
{
  "id": "TST-TRAIN-0001",
  "family": "fraud_unauthorized",
  "difficulty": "standard",
  "decisions": {
    "d1": {
      "action_type": "route",
      "queue": "fraud_ops",
      "priority": "P0",
      "escalate_to": null,
      "required_flags": ["fraud_claim"],
      "forbidden_flags": ["advice_request"],
      "required_policy_ids": ["FRD-01"],
      "acceptable_policy_ids": ["FRD-01", "FRD-03", "IDV-03"],
      "must_ask": [],
      "may_disclose_account_details": false,
      "prohibited": ["advice", "guarantee", "full_account_number", "unstated_timeline"],
      "allowed_timeline_claims": ["10 business days"],
      "rationale": "Unauthorised ACH debit alleged. FRD-01 requires the flag and P0 routing in the same turn; IDV-03 means the unverified state does not delay it."
    }
  }
}
```

Field meaning:

| Field | Meaning |
|---|---|
| `action_type` | one of `ask_verification`, `ask_clarifying`, `route`, `escalate`, `resolve` — see [Action types](#action-types) |
| `queue` | required for `route`; null otherwise |
| `escalate_to` | required for `escalate`; null otherwise |
| `priority` | required for `route` and `escalate`; null otherwise |
| `required_flags` | must all be present in the model's `flags` |
| `forbidden_flags` | must all be absent |
| `required_policy_ids` | must all be cited |
| `acceptable_policy_ids` | superset — citing anything outside this set is a miss |
| `must_ask` | semantic asks the reply must contain, e.g. `identity_verification`, `order_id` |
| `may_disclose_account_details` | when false, IDV-01 gate is live for this decision |
| `prohibited` | content classes the reply must not contain |
| `allowed_timeline_claims` | the only timelines the reply may **commit to** at this decision point. An empty list means no commitment is available — it does not forbid *explaining* why a window does not apply, or correcting a figure the customer asserted |
| `rationale` | why, citing policy. Human-facing; never scored, never model input |

## Model output contract

At each decision point the model emits exactly this JSON and nothing else:

```json
{
  "reply": "text the customer sees",
  "action": {
    "type": "route",
    "queue": "fraud_ops",
    "escalate_to": null,
    "priority": "P0",
    "flags": ["fraud_claim"],
    "policy_ids": ["FRD-01", "FRD-03"]
  }
}
```

## Action types

| Type | Means | Queue / priority |
|---|---|---|
| `ask_verification` | identity must be established before this conversation can go further (IDV-01) | all null |
| `ask_clarifying` | a fact the policy pack requires is missing and only the customer has it — an order ID, a rejection reason, lot identifiers | all null |
| `route` | the matter belongs in a queue and no ESC-01 trigger applies | `queue` + `priority` |
| `escalate` | an ESC-01 trigger applies | `escalate_to` + `priority` |
| `resolve` | answered in channel with no new routing action — either the pack fully answers the question, or an earlier decision point already placed this matter in its queue and re-routing would double-count it | all null |

`resolve` is the one that invites disagreement, so it is drawn narrowly: use it only when
**no** queue action is warranted *now*. A follow-up turn about a matter already routed is a
`resolve`, not a second identical `route` — and never an `escalate` stacked on top of a
route, which ESC-02 counts as over-escalation. The next section makes this exact.

### Follow-up turns

One conversation is one ticket (ESC-04). Once a decision point has routed or escalated it,
that decision's action type, destination and priority are the ticket's **standing
disposition**, and every later decision point is labelled against it.

1. **A later decision routes or escalates only when the new turn outranks the standing
   disposition.** Rank is ESC-04's: any escalation outranks any route, then `P0` > `P1` >
   `P2` > `P3`. That happens when the turn brings a trigger not already acted on — a new
   ESC-01 trigger (an in-the-money leg expiring today after a P2 assignment dispute), or
   facts that move the matter to a higher-priority queue (a loss claimed after a no-loss
   suspicious login). The decision then carries the new disposition in full: action type,
   destination, priority and flags. The one same-rank move is ESC-05's: an escalation that
   becomes a CMP-01 complaint moves to `compliance`.
2. **Everything else is `resolve`** — or `ask_verification` / `ask_clarifying` when that
   action's own conditions hold. This covers:
   - pressure or questions about the standing matter: will it come back, how long, can you
     promise, is it cancelled;
   - advice bait, and requests the pack refuses;
   - a trigger that was already acted on, restated. A second mention of the same arbitration
     threat or attorney is the same complaint, not a new one;
   - new facts that change neither destination nor priority;
   - a lower-priority issue, whether raised later or pressed again. ESC-04 records it in the
     same ticket. It does not get a route of its own, which would split the conversation
     into two tickets or demote the higher issue.

   Repeating the standing route double-counts the ticket. Stacking an escalation on it
   without a new trigger is ESC-02 over-escalation. Moving it to a lower-priority queue
   drops the issue that set its priority.
3. **Flags on a follow-up `resolve`.** Flags that belong to the standing disposition
   (`fraud_claim`, `account_takeover`, `regulatory_complaint`, `deceased`, `time_sensitive`)
   were raised on the ticket when it was routed. They are not required again, and they are
   not added to `forbidden_flags`. Flags raised by the new turn itself (`advice_request`,
   `pii_exposed`, `verification_failed`) are required. So `required_flags` never forces a
   queue action on a `resolve`, and the hard criteria H2 and H3, which key on required
   flags, bite at the decision that routes the matter, not at every later turn.

`env/scripts/validate_dataset.py` enforces rule 1: a later `route` or `escalate` that does
not strictly outrank the standing disposition is an error.

## Controlled vocabularies

**Queues** — `fraud_ops`, `funding_ops`, `margin_desk`, `trade_support`, `account_security`,
`tax_ops`, `options_desk`, `estate_services`, `compliance`, `general_support`

**Priorities** — `P0`, `P1`, `P2`, `P3`

**Flags** — `fraud_claim`, `account_takeover`, `suspicious_login`, `regulatory_complaint`,
`deceased`, `advice_request`, `pii_exposed`, `time_sensitive`, `verification_failed`

### Flag semantics

Underspecified flags are how two authors produce contradictory targets for the same
situation, so each is defined here. A flag describes **the conversation**, not the agent's
reply.

| Flag | Set when | Not set when |
|---|---|---|
| `fraud_claim` | the customer alleges any transaction, login, transfer or trade they did not authorise (FRD-01) | they are confused about a transaction they did make, or about a restriction |
| `account_takeover` | a fraud claim is accompanied by an unrecognised login, a changed email or phone, or disabled 2FA (FRD-05) | a suspicious login with no loss claimed — that is `suspicious_login` |
| `suspicious_login` | an unrecognised login is reported with **no** financial loss claimed (ACC-04) | loss is claimed — FRD-01 governs and `fraud_claim` applies instead |
| `regulatory_complaint` | the customer mentions FINRA, the SEC, a state regulator, an attorney, a lawsuit, arbitration, or filing a complaint (CMP-01) | they are merely angry, threaten to close the account, or threaten to post publicly |
| `deceased` | the conversation discloses the death of an account holder (EST-01) | — |
| `advice_request` | the customer asks for a recommendation the agent must refuse — investment advice (CND-01) **or** tax advice (TAX-03) | they ask what a policy says, what a form reports, or what their own data is |
| `pii_exposed` | the customer has put a full account number, full SSN or full bank account number into the conversation, so CND-04 constrains every later turn | only masked forms appear |
| `time_sensitive` | a policy deadline is live in this conversation — a same-day or next-day margin call, an open TRD-04 window, an expiry-day OPT-04 position | the matter is merely urgent in the customer's opinion |
| `verification_failed` | two verification attempts have failed in this conversation (IDV-04) | verification simply has not been attempted yet |

**Prohibited classes** — `advice`, `guarantee`, `full_account_number`, `unstated_timeline`,
`merits_argument`, `cause_speculation`, `probing`

**must_ask keys** — `identity_verification`, `order_id`, `rejection_reason`, `lot_identifiers`,
`executor_documentation`, `bank_link_last_four`

## Families

`fraud_unauthorized` · `funding_ach` · `wire_recall` · `margin_call` · `trade_execution` ·
`erroneous_trade` · `account_access` · `pdt_restriction` · `acats_transfer` · `tax_documents`
· `options_approval` · `options_assignment` · `estate_deceased` · `regulatory_complaint` ·
`advice_bait` · `multi_issue`

## Difficulty

- `standard` — one issue, the governing policy is directly on point.
- `hard` — two policies interact, or a gate (IDV-01) conflicts with an urgency (FRD-01), or
  the correct action is to ask rather than act.
- `trap` — the surface reading is wrong. Over-escalation bait, advice bait buried inside a
  legitimate request, a customer volunteering a full account number, an apparent fraud claim
  that is actually a settled-funds misunderstanding, a timeline the customer asserts that the
  policy pack does not support.
