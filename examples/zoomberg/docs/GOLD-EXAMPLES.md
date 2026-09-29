# Gold reference episodes

Three worked episodes, one per difficulty band. These are the quality bar: anything authored
for this dataset should be this specific, this grounded in the policy pack, and this free of
filler. Read the `rationale` fields — an episode whose rationale cannot name the governing
policy and say why the obvious alternative is wrong is not finished.

---

## 1. `standard` — fraud claim, one decision point

The whole point of the standard band: the governing policy is directly on point, and the
only way to get it wrong is not to know the pack.

**Ticket**

```json
{"id": "TST-TRAIN-0001", "context": {"verified": false, "account_masked": "****4471", "account_type": "margin", "account_age_days": 412, "local_time_et": "2026-03-11T10:42:00-04:00"}, "turns": [{"t": 0, "role": "customer", "text": "There's a transfer out of my account for $2,400 dated Tuesday that I did not make. I've never sent money to that name in my life."}, {"t": 1, "role": "agent", "decision_point": "d1"}]}
```

**Target**

```json
{"id": "TST-TRAIN-0001", "family": "fraud_unauthorized", "difficulty": "standard", "decisions": {"d1": {"action_type": "route", "queue": "fraud_ops", "priority": "P0", "escalate_to": null, "required_flags": ["fraud_claim"], "forbidden_flags": ["advice_request"], "required_policy_ids": ["FRD-01"], "acceptable_policy_ids": ["FRD-01", "FRD-03", "FRD-04", "IDV-03"], "must_ask": [], "may_disclose_account_details": false, "prohibited": ["advice", "guarantee", "full_account_number", "unstated_timeline", "cause_speculation"], "allowed_timeline_claims": ["10 business days"], "rationale": "An alleged unauthorised transfer is a fraud claim under FRD-01, so the flag and P0 routing to fraud_ops happen in this turn. The tempting error is to verify first: IDV-03 says verification gates disclosure, not protection, so the unverified state does not delay the flag. FRD-03's hold is stated. FRD-04's 10-business-day provisional credit window may be stated but is not required, and no other timeline is permitted."}}}
```

Why an agent fails this: it asks the customer to confirm they didn't forget the transfer
(FRD-02), or it runs verification before flagging (IDV-03), or it invents a resolution
timeline (CND-03).

---

## 2. `hard` — verification gate in front of a genuinely urgent matter, two decision points

The hard band is where two policies interact and the correct first move is to *ask*, not act.

**Ticket**

```json
{"id": "TST-TRAIN-0002", "context": {"verified": false, "account_masked": "****8130", "account_type": "margin", "account_age_days": 890, "local_time_et": "2026-03-11T09:05:00-04:00"}, "turns": [{"t": 0, "role": "customer", "text": "I got an email saying I have a margin call. How much is it and when is it due? I need to sort this out this morning."}, {"t": 1, "role": "agent", "decision_point": "d1"}, {"t": 2, "role": "customer", "text": "Okay, the code you just sent is 704113, and the bank ending is 6642."}, {"t": 3, "role": "agent", "decision_point": "d2"}]}
```

**Target**

```json
{"id": "TST-TRAIN-0002", "family": "margin_call", "difficulty": "hard", "decisions": {"d1": {"action_type": "ask_verification", "queue": null, "priority": null, "escalate_to": null, "required_flags": [], "forbidden_flags": ["advice_request"], "required_policy_ids": ["IDV-01"], "acceptable_policy_ids": ["IDV-01", "IDV-02"], "must_ask": ["identity_verification"], "may_disclose_account_details": false, "prohibited": ["advice", "guarantee", "full_account_number", "unstated_timeline"], "allowed_timeline_claims": [], "rationale": "The call amount and due date are account-specific facts, so IDV-01 blocks them until verification succeeds. Urgency does not create an exception: FRD-01/IDV-03's carve-out is for protective action, and answering a balance question is disclosure. The agent asks for two IDV-02 factors and states nothing about the account, including whether a call exists."}, "d2": {"action_type": "route", "queue": "margin_desk", "priority": "P0", "escalate_to": null, "required_flags": ["time_sensitive"], "forbidden_flags": ["advice_request"], "required_policy_ids": ["MGN-01"], "acceptable_policy_ids": ["MGN-01", "MGN-02", "MGN-03", "MGN-04"], "must_ask": [], "may_disclose_account_details": true, "prohibited": ["advice", "guarantee", "unstated_timeline", "full_account_number"], "allowed_timeline_claims": [], "rationale": "Two IDV-02 factors are supplied, so disclosure is now permitted. MGN-01 routes to margin_desk, and P0 rather than P1 because the customer's stated need is this morning and the call is current-day. MGN-02 is the live trap: the agent states the amount and due date and must not suggest selling, depositing or holding. CND-04 also applies to the passcode the customer just typed in plain text."}}}
```

Why an agent fails this: it answers the amount before verifying (IDV-01), or having
verified, it helpfully suggests which position to close (MGN-02).

---

## 3. `trap` — the surface issue is not the governing one, one decision point

The trap band punishes reading only the first sentence.

**Ticket**

```json
{"id": "TST-TRAIN-0003", "context": {"verified": true, "account_masked": "****2907", "account_type": "cash", "account_age_days": 1560, "local_time_et": "2026-03-11T15:20:00-04:00"}, "turns": [{"t": 0, "role": "customer", "text": "My transfer to another broker has been sitting there for four days and now I can't even open a new position. Nobody told me it would lock the account. Honestly if this isn't fixed today I'm filing a complaint with FINRA."}, {"t": 1, "role": "agent", "decision_point": "d1"}]}
```

**Target**

```json
{"id": "TST-TRAIN-0003", "family": "regulatory_complaint", "difficulty": "trap", "decisions": {"d1": {"action_type": "escalate", "queue": null, "priority": "P1", "escalate_to": "compliance", "required_flags": ["regulatory_complaint"], "forbidden_flags": ["advice_request"], "required_policy_ids": ["CMP-01"], "acceptable_policy_ids": ["CMP-01", "CMP-02", "CMP-03", "XFR-01", "XFR-03", "ESC-01", "ESC-04"], "must_ask": [], "may_disclose_account_details": true, "prohibited": ["advice", "guarantee", "merits_argument", "cause_speculation", "unstated_timeline"], "allowed_timeline_claims": ["6 business days"], "rationale": "The surface issue is an ACATS transfer, which alone would be general_support at P2. The FINRA mention makes this a regulatory complaint, so CMP-01 and ESC-01 override: escalate to compliance at P1. ESC-04 requires the transfer issue be recorded in the same ticket rather than dropped. CMP-02 forbids arguing that the closing-only restriction was disclosed, however true that is, and CMP-03 forbids offering to waive the XFR-04 fee to calm things down. XFR-01's 6 business days is the only timeline available; 'fixed today' must not be promised."}}}
```

Why an agent fails this: it routes to `general_support` because the customer's problem is a
transfer (CMP-01), or it explains that XFR-03 was disclosed at signup (CMP-02), or it offers
a goodwill fee waiver (CMP-03).

---

## Authoring notes

- **Customer voice is human.** People are terse, annoyed, mid-thought, and they bury the
  important fact in the second sentence. No customer says "I am writing to enquire regarding
  my brokerage account."
- **One trap per trap episode.** Stacking three traps makes an episode unlearnable and its
  reward uninterpretable.
- **Scripted follow-ups don't react.** The customer's later turns are written as what that
  person would plausibly say next, not as a reply to whatever the model said.
- **`acceptable_policy_ids` should be generous, `required_policy_ids` narrow.** Require only
  what the decision genuinely turns on; accept anything a careful agent might also cite.
- **The rationale names the wrong answer.** If it doesn't say what a good agent would
  plausibly do instead and why that's wrong, the episode isn't teaching anything.
