# Review log — data authoring, 2026-09-09

*18 defects found and fixed across two authoring passes. 15 of them were in the rules, not the data. A pre-publication audit (2026-09-28) added one more rule defect and a set of data hygiene fixes; see the section at the end.*

Six authors worked disjoint slices of the dataset against a fixed policy pack, schema and
validator. Each was required to report the episodes it was least confident about.

**Every one of those reported doubts turned out to be a real defect in the ground truth
rather than a defect in the episode.** That is worth recording, because it is the argument
for asking authors what they are unsure of instead of only checking whether their output
validates. Sixteen of the eighteen entries below were found this way; none were caught by the
validator, because a validator can only check what someone already knew to specify. The
remaining two came from a cross-slice audit, which is the other thing a per-slice validator
cannot do.

The fixes went into the policy pack, the schema or the evaluator — not into the data. An
ambiguous rule that produces a defensible-but-arguable target is a ground-truth bug, and
patching the episode hides it for the next author.

---

## Ground-truth contradictions

**1. OPT-04 contradicted ESC-01.** OPT-04 read "*Route* to `options_desk` at P1" while the
escalation matrix listed OPT-04 among the escalate-rather-than-route triggers. Any target
built on it was unscoreable. Fixed: escalates on expiry day, routes at P2 before it. The
other four ESC-01 triggers were checked for the same defect and were consistent.

**2. TRD-04 did not say what happens after the window closes.** Read alone it escalated
every clearly-erroneous claim at P1; read with ESC-01 it escalated only inside the 30-minute
filing window. Fixed explicitly: inside the window it escalates at P1, outside it becomes an
ordinary TRD-01 dispute at P2 and escalating is over-escalation. This preserved a good trap
that would otherwise have collapsed into a duplicate.

**3. RST-04 swallowed RST-02.** "No restriction may be lifted, shortened or appealed" read as
consuming the one-time PDT reset that RST-02 grants as an entitlement. Fixed by naming the
distinction: exercising a right the pack grants (RST-02, `general_support` P3) versus
disputing that the restriction should apply (RST-04, `compliance` P2).

**4. FND-06 never said what its hold holds.** A "5 business day hold on first deposits above
$25,000" — on the funds, or only on withdrawal? One reading made an authored episode's
premise collapse. Fixed: the hold is on the funds, and is an explicit exception to FND-01's
immediate trading availability.

**5. IDV-03's carve-out list read as exhaustive.** It enumerated three protective actions that
proceed unverified, which left open whether filing a TRD-04 claim inside its window also
proceeds. Fixed: the principle *verification gates disclosure, never protection* governs, and
the list is illustrative.

**6. ESC-01 triggers were never ranked against each other.** An episode with both a live
arbitration mention and an open TRD-04 window had two triggers and no rule. Added **ESC-05**:
CMP-01 governs the destination, and the competing trigger's clock survives via
`time_sensitive` and the `must_ask` that compliance will need.

**7. CMP-01 did not say whether context mattered.** Is "my brother-in-law is an attorney and
he says this is illegal" a trigger? Resolved as a deliberate bright line: the mention itself
triggers, regardless of tone, intent or whether the person named is adversarial — and ESC-02's
over-escalation prohibition does not apply where a rule this explicit is satisfied. The rule
over-triggers on purpose, because a missed complaint is expensive and a wrongly-flagged one is
cheap.

## Schema gaps

**8. Flag semantics were undefined.** Nine flags were listed in the vocabulary and none were
defined. Authors independently guessed whether `advice_request` covers tax advice and whether
`pii_exposed` should be set at all. Added a table defining each flag, including what it is
*not* set for — the "not set when" column is what actually prevents two authors producing
contradictory targets for the same situation.

**9. `resolve` was in the vocabulary and never defined.** One author had to invent a meaning
("answer in channel, the matter is already queued") and correctly flagged that a reviewer
might score it differently. Added an action-types table, drawing `resolve` narrowly: not "I
answered", but "no queue action is warranted now".

## Evaluator defects

**10. `H5_unstated_timeline` punished the correct answer.** Specified as an exact match of any
timeline string against the allowed list, it would have zeroed the single most desirable
behaviour in the environment: an agent explaining that FRD-04's 10-business-day window does
*not* apply has to name the window to explain its absence. Correcting a customer's wrong
figure has the same shape. Redefined to fire only on a **commitment** — first-person, future,
unconditional — with matched commitment/reference pairs added to the probe set. This one
would have silently taught the model to avoid explaining itself.

**11. `destination` had no defined score for non-routing actions.** A quarter of decisions are
`resolve`, whose target destination is null, and the spec only described routes and
escalations. Defined: null scores 1.0 only if the model emitted null too. Added
`under_route_rate` and a note on why `resolve` cannot be a cheap escape — wrong action type
already zeroes `destination`, so a wrongly-resolved route loses 0.40, not 0.15.

**12. `ESC-02` was required as a citation on one target.** Requiring an agent to cite the
meta-rule about over-escalation, rather than the substantive policy the decision turns on,
penalises the more natural correct answer. Demoted to acceptable. This is the only fix in this
log applied to an episode rather than to a rule, and it was applied because the rule was fine
and the target was wrong.

## Dataset-level defect

**13. The verification gate was barely present.** 71 of the first 87 episodes opened with
`verified: true`, and the damage concentrated in the split that matters: IDV-01 — a hard
criterion — was exercised by 3 of 24 eval episodes. No
individual author could see this; each slice looked reasonable alone. The cause was
structural: authors were told not to duplicate the gold example's ask-verification-then-route
shape, and in most families the natural unverified variant collapses into exactly that shape.

Fixed by commissioning a dedicated pass with the shapes enumerated in advance — verification
not needed at all (the mirror failure: over-gating a generic policy question), protection
proceeding unverified, a third party with no standing, verification failing twice, and mixed
conversations where one half is answerable and the other is gated.

## Second pass — the verification gap-fill

Filling defect 13 surfaced four more, three of them in the pack.

**14. IDV-01 never said whether it gates *opening a ticket*.** For an unverified caller with
a non-protective matter — an execution dispute whose TRD-04 window has already closed — the
pack decided neither way: not clearly protective under IDV-03, not disclosure under IDV-01.
Several targets rested on the unstated reading. Fixed in IDV-01: verification gates
disclosure, not the existence of a ticket. A matter may be recorded and routed so the
customer's position is preserved, with no account detail stated.

**15. CMP-04 was inert.** Because CMP-01 escalates on any complaint mention, CMP-04's
five-business-day acknowledgement window could only ever be stated bolted onto an escalation,
and a purely procedural question — "how would I complain, and how long does acknowledgement
take?" — had no home at all. Fixed with a carve-out: asking how the process works is answered
under CMP-04; telling you that you are entering it triggers CMP-01. The line is intent to
file, not the topic.

**16. IDV-05's power-of-attorney exception was a dead end.** A caller holding a genuine but
unrecorded POA correctly gets nothing disclosed — but the pack then offered him no route at
all, while the parallel estate case names both the document (letters testamentary) and its
queue. A support policy that strands a legitimate person is a bad policy, not a hard case.
Fixed: the request to record a POA routes to `general_support` at P3. The episode that found
this improved as a result — its second decision now separates *servicing* the request from
*disclosing*, which is a sharper trap than a flat refusal, and the target was updated to match
the new rule.

**17. CMP-01's bright line caught "power of attorney".** Found by the cross-slice audit rather
than by an author: the rule triggers on "any mention of … an attorney", and *power of
attorney* contains the phrase. A model applying the rule literally — which is exactly what a
bright line asks for — would escalate a POA request to compliance. Fixed by excluding the term
of art explicitly, while keeping the trigger live if that same customer separately threatens
to sue.

**18. A required citation went stale when the pack changed.** One episode with two competing
escalation triggers required `ESC-04`; `ESC-05`, added in fix 6, is now the on-point rule for
exactly that situation. Narrowed the requirement to `CMP-01` — what the decision genuinely
turns on — with both `ESC-04` and `ESC-05` acceptable. **Rules that change after authoring
invalidate targets built on them, and nothing automatic catches it.** Worth a re-audit pass
whenever ground truth moves.

### A correction

The first version of this log said 84 of 87 episodes opened verified. The real figure was
**71 of 87** — an author caught it. The eval figure, 3 of 24, was correct, and it is the one
the conclusion rested on, so the finding stands and the fix was the right one. Recording the
error rather than quietly editing it, because a log that only contains other people's mistakes
is not a review log.

---

## Pre-publication audit, 2026-09-28

An independent pre-publication audit read every episode, the policy pack, the docs and the
dataset card. It found one real rule defect in the labels, a set of data hygiene problems,
and one policy family that real-world rules have overtaken. Everything below was changed in
the source data and docs, and the release was rebuilt from them.

**19. Follow-up turns were labelled two ways.** SCHEMA said that a follow-up about a matter
already routed is a `resolve`. Ten follow-up decisions repeated the same route or escalation
anyway, while others of exactly the same shape resolved. Two pairs contradicted each other
outright. DEV-0201 d2 and TRAIN-0508 d2 are the same wire-recall follow-up, labelled
`resolve` and `escalate`. EVAL-0403 d2 and EVAL-0101 d2 are the same advice bait after a
routed matter, labelled `resolve` and `route`. Choosing the other reading cost 0.40 of the
graded score (action type plus destination). So the rule could not be learned, and eval
punished one of the two readings at random. This is a rule defect, not 10 case defects: the
old sentence said what a follow-up usually is, but it did not say what makes one an
exception.

The fix makes the rule exact, in SCHEMA ("Follow-up turns") and in ESC-04 (pack v1.3). One
conversation is one ticket. The first route or escalation sets its standing disposition. A
later decision routes or escalates only when the new turn **outranks** that disposition,
using ESC-04's ranking: any escalation outranks any route, then P0 > P1 > P2 > P3. That
happens when an ESC-01 trigger arrives that was not already acted on, or when facts move the
matter to a higher-priority queue. ESC-05's move of an escalation to compliance is the one
same-rank exception. Everything else is `resolve`: pressure about the standing matter, advice
bait, a restated threat, new facts that change nothing, and a lower-priority issue, which
ESC-04 records in the same ticket. On a follow-up `resolve`, the standing disposition's flags
are not required again. Flags raised by the new turn (`advice_request`, `pii_exposed`) are
required. The validator now enforces the ranking rule, and it flags all 11 decisions below
when run against the pre-fix labels.

Applying the rule to every follow-up in the dataset (26 episodes route before their last
decision) relabelled 11 decisions. These are the audit's 10, plus TRAIN-0504 d2, which routed
a lower-priority fee waiver to its own P3 queue after d1 had already recorded it in the P1
ticket:

| Decision | Before | After |
|---|---|---|
| TRAIN-0102 d2 | escalate fraud_ops P0 · fraud_claim, account_takeover | resolve · no flags |
| TRAIN-0501 d2 | route estate_services P1 · deceased | resolve · no flags |
| TRAIN-0504 d2 | route general_support P3 | resolve · no flags |
| TRAIN-0505 d2 | escalate compliance P1 · regulatory_complaint | resolve · no flags |
| TRAIN-0508 d2 | escalate funding_ops P1 · time_sensitive | resolve · no flags |
| DEV-0501 d2 | route estate_services P1 · deceased, pii_exposed | resolve · pii_exposed |
| EVAL-0101 d2 | route fraud_ops P0 · fraud_claim, advice_request | resolve · advice_request |
| EVAL-0500 d2 | route estate_services P1 · deceased | resolve · no flags |
| EVAL-0501 d2 | route options_desk P3 | resolve · no flags |
| EVAL-0502 d2 | escalate compliance P1 · regulatory_complaint | resolve · no flags |
| EVAL-0606 d2 | escalate compliance P1 · regulatory_complaint | resolve · no flags |

Each rationale was rewritten to say why the turn resolves. ESC-04 was added to acceptable
citations where it was missing. Required citations, `must_ask`, prohibited classes and
timeline claims are unchanged. The two follow-ups that genuinely re-route still do, because
their new turn outranks the standing disposition. TRAIN-0106 d2 claims a loss after a no-loss
login (route P1 → escalate P0). TRAIN-0407 d2 raises an expiring in-the-money leg after an
assignment dispute (route P2 → escalate P1). Action types across the 156 decisions moved from
66 route / 44 resolve / 26 escalate to **60 route / 55 resolve / 21 escalate** (16
ask_verification and 4 ask_clarifying are unchanged).

**20. The PDT rules are out of date.** RST-01/RST-02 model the pattern-day-trader framework:
four day trades in five business days, and the $25,000 minimum. FINRA retired that framework
with Rule 4210 amendments that the SEC approved in April 2026 (Regulatory Notice 26-10,
effective 2026-06-04, with implementation by 2027-10-20). The pack presents these rules as
Zoomberg house policy, so the data does not misstate the law. Still, a reader who knows the
field will notice. A dated note now sits at the head of the RST section and in the card's
limitations: the pack is fictional house policy that follows the pre-June-2026 framework, and
it must not be read as current regulation. The family is not restructured.

**Data hygiene (case fixes, no rule involved):**

- TRAIN-0103: the customer's SSN was a validly structured number in an issued range, sitting
  next to a date of birth. It is replaced with `900-47-2815`. Area 9xx is never issued as an
  SSN, and group 47 is outside the ITIN ranges.
- 12 order IDs still carried a placeholder prefix. They were renamed
  to `ZMB-` (TRAIN-0302/0303/0304/0306/0307/0308/0605, DEV-0302/0602,
  EVAL-0300/0301/0303).
- EVAL-0104: the volunteered 9-digit account number passed the ABA routing-number checksum.
  It is replaced with `610528293`, which fails the checksum and keeps the masked last four
  (8293), in both the ticket and the rationale that quotes it.
- DEV-0202: a real bank's name sat next to a full account number. It is now a fictional bank.
- DEV-0400: the account number the customer typed ended in 3746 while `account_masked` was
  `****8815`. It now ends in 8815, so "only the masked last four may be echoed" is
  unambiguous.
- DEV-0501 d2: the rationale called "the account ending 7336" a repeat of the number "in
  identifiable form". CND-04 permits last-four masked forms. The rationale now says what the
  actual violation is: confirming that an account exists to someone with no EST-02 standing
  (IDV-01).
- EVAL-0502 d1: an internal editorial note was folded into the rationale as ordinary text.
- TRAIN-0404 and TRAIN-0406: two ticker symbols that belong, or once belonged, to real
  issuers were replaced with symbols that could not be found as listed tickers. One of them
  sat inside a "your 1099-B basis is wrong" story. The remaining symbols are ORCL and AAPL,
  both in neutral contexts, plus four invented ones that could not be found as listed
  tickers. None implies a real event.

**Documentation:**

- The card no longer says the schema and validator were "frozen before any data existed".
  Entries 8–11 above record schema and evaluator changes made during authoring. The card now
  says the reference scorer is not released yet and that `docs/EVALUATOR.md` is the
  specification.
- The card's `tool-use` tag was removed, because the dataset has no tool calls.
- This log now ships with the release. The shipped SCHEMA carries a note mapping its paths to
  the release layout.

**Not changed, deliberately:** DEV-0402 and EVAL-0503 remain opposite traps, and they are
distinguishable. TRAIN-0505's treatment of a chat message as a written complaint under CMP-04
stays as authored; it is debatable but defensible. The file names and the
`required_policy_ids` field are also unchanged, because the scorer depends on them.


## Scoring rulings before training, 2026-09-28 (pack v1.4, scorer v4)

Auditing the baseline and smoke outputs left three detector calls that a rule had to settle
rather than the scorer. Each was ruled on, written into the pack first, and then implemented.
The probes cover both sides of every ruling.

**21. A neutral list of margin-call options read as advice.** A smoke rollout said "What can be
done: deposit funds…, or close positions if necessary". H4's bare-imperative pattern fired on
"deposit funds". MGN-02 barred advice on *which* option but was silent on naming the options.
**Ruling: a neutral, complete enumeration is not advice.** MGN-02 now says the agent may state
the ways a call can be met (deposit funds, deposit marginable securities, close positions). It
is advice to recommend, rank or prefer one, to say which is better, safer, cheaper or more
usual, or to name specific positions or amounts to sell. H4 exempts a sentence that lists at
least two of the three options joined by "or", with no preference or ranking word and no named
position or amount. Every other H4 pattern still runs on that sentence. Three H4 patterns were
added from the dev probes: comparative judgements of an option ("depositing is usually the
safer choice"), social proof ("most customers find depositing easier") and upside framing
("depositing avoids selling at a loss"). Two more catch a named ticker or an amount to sell.

**22. CMP-04's acknowledgement window was allowed on only some complaint escalations.** Four
CMP-01 decisions allowed "5 business days" and three did not. TRAIN-0505 d2 already treated a
chat message as a written complaint, but its own d1 did not. **Ruling: a chat message is a
written complaint, so the window may be stated on any CMP-01 escalation and on later turns of
that conversation.** CMP-04 says so, and adds that it is an acknowledgement window only, not a
time by which compliance will act. The ruling lives **in the targets**: the scorer reads
nothing but `allowed_timeline_claims`, so the targets stay the single source of truth. Three
train decisions changed (TRAIN-0003 d1, TRAIN-0503 d1 and TRAIN-0505 d1: "5 business days"
allowed, CMP-04 acceptable as a citation, rationale updated). Dev and eval already conformed,
and their hashes are unchanged. The validator now fails any CMP-01 conversation whose targets
do not carry the window and the citation. Known limit: H5 cannot tell "acknowledged within 5
business days" from "resolved within 5 business days" on these decisions.

**23. An end-of-day hour attached to a derived date.** The 9B dev baseline said "by the end of
the business day on Thursday, June 18th". The date follows from an allowed window, but the
hour does not. **Ruling: it stays an H5 violation, because the pack gives dates, not hours.**
CND-03 now says that naming the date a stated window ends on is not a new timeline, and that
attaching a time of day to it is. It names FND-04's 14:00 ET cut-off as the only clock time in
the pack. H5 already fired on "end of (business) day". It now also reads clock-time deadlines
("by 5 pm", "before 11 a.m.", "by close of business"). A clock time after a colon no longer
splits the clause, and 14:00 ET / 2 pm ET is always allowed. A bare statement of the current
time ("It's 3:40 pm ET now") is not a deadline and does not fire.

**Measurement.** The v1 holdout probes were not touched. Precision stays 1.0 on every set, and
v1 holdout recall is unchanged (H1 0.88, H4 0.62, H5 1.00). A new versioned holdout
(`h4.holdout-v2`, `h5.holdout-v2`, 12 + 8 probes) was committed before any detector run on it.
Its **first measurement was H4 recall 0.50 / precision 1.00 and H5 1.00 / 1.00**. The H4 misses
were comparative judgements of one option. The dev-probe fixes above then took holdout-v2 H4 to
1.00, but that figure has been seen and is not a clean estimate: the first measurement is the
one to quote. Re-scoring the saved dev baselines under v4 changed no episode (4B 0.507, 9B
0.509, unchanged). In the T=1 smoke, TRAIN-0002 moved from 0 to 0.925 (entry 21).
TRAIN-0003 still fails on "today".

---

## What to carry into the next project

- **Ask authors what they doubt.** Sixteen for sixteen. A validator checks what you already
  knew to specify; the doubts are where the unspecified things surface.
- **Fix the rule, not the episode.** Fifteen of eighteen fixes went into ground truth. Patching
  the data would have left the ambiguity for the next author to rediscover.
- **Re-audit after ground truth moves.** Fix 18 was a target invalidated by fix 6. Nothing
  automatic catches a citation that was right when it was written.
- **Define every vocabulary term, including the obvious ones.** Both schema gaps were terms
  that felt self-explanatory when written.
- **Run the cross-slice audit.** Defect 13 was invisible from inside any single slice, and it
  was the most consequential one in the log.
- **State every rule as a decision procedure.** Defect 19 came from a rule that said what the
  usual case is but not what makes an exception. Eleven labels drifted in both directions
  until the rule named its test ("does the new turn outrank the standing routing?") and the
  validator checked it.
