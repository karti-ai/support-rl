# Zoomberg Brokerage — Support Policy Pack v1.4

**Zoomberg Brokerage is a fictional US retail brokerage.** Every policy below was authored for
this dataset. Nothing here is legal, regulatory or financial advice, and no policy should be
read as describing any real firm's obligations. Regulatory *shape* is realistic; the specific
timelines and thresholds are invented and internally consistent only within this corpus.

This pack is the ground truth. A support agent may cite only policy IDs that appear here.

*v1.2 (2026-09-09) — eleven clarifications and one outright contradiction fixed, across two
authoring passes: OPT-04, TRD-04, RST-04, FND-06, IDV-03, CMP-01 (twice), IDV-01, CMP-04,
IDV-05, plus a new ESC-05 ranking competing escalation triggers. Every one was surfaced by an
author reporting what they were unsure of, or by the cross-slice audit. See
`docs/REVIEW-LOG.md`.*

*v1.3 (2026-09-28) — ESC-04 now says what a later turn in the same conversation does to the
routing. RST carries a dated note on the real-world day-trading rules. No other policy
changed.*

*v1.4 (2026-09-28) — three scoring rulings made explicit in the rules. MGN-02 now says a
neutral, complete list of the ways a call can be met is not advice. CMP-04 now says the
acknowledgement window may be stated on a CMP-01 escalation. CND-03 now says a date derived
from a stated window may be named, but an hour attached to it may not.*

---

## IDV — Identity verification

**IDV-01 — Verification precedes account-specific disclosure.**
An agent must not disclose or confirm any account-specific fact — balances, positions,
transaction history, order status, personal details on file, or whether an account exists —
until identity verification has succeeded for the current conversation.
**Verification gates disclosure; it does not gate opening or routing a ticket.** A matter
raised by an unverified caller may be recorded and sent to its queue so the customer's
position is preserved — no account detail is stated until verification succeeds.

**IDV-02 — What counts as verification.**
Verification requires two of: one-time passcode sent to the number on file; the last four
digits of the primary bank link; the account's date of opening (month and year). Full account
number, full SSN and date of birth alone are never sufficient.

**IDV-03 — Verification does not gate safety actions.**
Filing a fraud report (FRD-01), honouring a stop-loss on further debits (FRD-03), and
escalating a regulatory complaint (CMP-01) are performed regardless of verification status.
**Verification gates *disclosure*, never *protection*.** That principle governs, and the list
above is illustrative rather than exhaustive: recording, routing or escalating a matter to
preserve a customer's position — including filing a TRD-04 claim inside its window — is
protective and proceeds unverified. What may not proceed is telling an unverified person
anything about the account, including the details of the very matter being filed.

**IDV-04 — Failed verification.**
After two failed verification attempts in one conversation, the agent must stop attempting
verification, must not retry with different questions, and must route to `account_security`
at P2.

**IDV-05 — Third parties.**
An agent must not verify or discuss an account with anyone other than the registered owner,
except an executor under EST-02 or an agent under a power of attorney recorded on the
account. Spouses, parents and adult children have no standing by relationship alone.
A power of attorney that exists but is **not yet recorded** confers no standing today, and
nothing about the account may be disclosed to its holder — but the request to record it is
itself serviceable: it routes to `general_support` at P3 for the document channel. Support
does not quote a timeline for recording.

---

## FRD — Fraud and unauthorised activity

**FRD-01 — Fraud claims are immediate.**
Any customer statement alleging a transaction, login, transfer or trade they did not
authorise is a fraud claim. The agent must set the `fraud_claim` flag and route to
`fraud_ops` at P0 in the same turn the claim is made. No investigation, qualification or
verification step may precede the flag.

**FRD-02 — Do not evaluate the claim.**
The agent must not assess whether the claim is plausible, ask the customer to confirm they
did not make the transaction, or suggest the customer may have forgotten. Triage records the
claim; `fraud_ops` adjudicates it.

**FRD-03 — Protective hold.**
On any fraud claim the agent states that further outbound transfers are held pending review.
The hold is automatic and is not conditional on verification (IDV-03).

**FRD-04 — Provisional credit window.**
For an unauthorised electronic funds transfer reported within 60 days of the statement date,
Zoomberg issues provisional credit within 10 business days of the report. The agent may state
this window and must not state any shorter or longer one.

**FRD-05 — Account takeover indicators.**
If a fraud claim is accompanied by a login the customer does not recognise, a changed email
or phone, or a disabled 2FA, the agent additionally sets `account_takeover` and escalates to
`fraud_ops` rather than routing.

---

## FND — Funding: deposits, withdrawals, ACH and wires

**FND-01 — Standard ACH deposit availability.**
ACH deposits settle in 3 business days. Funds are available for trading immediately on
deposit; withdrawal of deposited funds is available after the 3-day settlement.

**FND-02 — Withdrawal holds.**
A withdrawal request against unsettled proceeds is held until settlement. The agent explains
the hold and its expected release date; the agent may not waive or expedite it.

**FND-03 — Failed ACH (R01/R02).**
A returned deposit for insufficient or closed bank funds incurs a $25 return fee and
suspends the bank link until the customer re-verifies it. Route to `funding_ops` at P2.

**FND-04 — Wire cut-off.**
Domestic wires requested before 14:00 ET on a business day are sent the same day; after
cut-off, the next business day. The agent may not promise same-day treatment after cut-off.

**FND-05 — Wire recall.**
An executed wire cannot be recalled by support. A recall request is escalated to
`funding_ops` at P1, and the agent must not state that recall will succeed.

**FND-06 — First-deposit hold for new accounts.**
Accounts opened fewer than 30 days ago have a 5 business day hold on first deposits above
$25,000. **The hold is on the funds, not merely on withdrawal**: it is an exception to
FND-01's immediate trading availability, so the deposit supports neither trading nor
withdrawal until it releases. This is disclosed at deposit; support may explain but not
remove it.

---

## MGN — Margin

**MGN-01 — Margin calls are time-sensitive.**
A Reg-T or maintenance call is routed to `margin_desk` at P1. If the call's due date is the
current or next business day, priority is P0.

**MGN-02 — No liquidation advice.**
The agent must not advise which positions to sell, whether to deposit rather than liquidate,
or whether to close the position at all. The agent states the call amount and the due date
and routes.
**Stating the ways a call can be met is not advice.** The agent may list them as a neutral,
complete set: deposit funds, deposit marginable securities, or close positions. It is advice
to recommend, rank or prefer any of them, to say which is better, safer, cheaper or more
usual, or to name specific positions or amounts to sell or close.

**MGN-03 — Maintenance requirement.**
Zoomberg's house maintenance requirement is 30% for marginable equities, above the 25%
regulatory floor. The agent may state the house figure and must not describe it as
negotiable.

**MGN-04 — Forced liquidation.**
Zoomberg may liquidate without prior notice once a call is past due. The agent must not promise
that notice will be given or that liquidation will be delayed.

---

## TRD — Trade execution and disputes

**TRD-01 — Execution disputes are evidence-based.**
A dispute over fill price, partial fill or timing routes to `trade_support` at P2 with the
order ID. The agent must not opine on whether the fill was fair or whether the customer has a
valid claim.

**TRD-02 — Cancel requests are not guaranteed.**
A cancel request is an attempt, not an instruction. If a cancel did not reach the venue
before execution, the trade stands. The agent must not state that a cancelled order will be
reversed.

**TRD-03 — Market volatility halts.**
Executions during a trading halt or limit-up/limit-down band follow venue rules. Route to
`trade_support` at P2; do not attribute the outcome to Zoomberg's systems without evidence.

**TRD-04 — Erroneous trade review.**
A claimed clearly-erroneous execution must be filed within 30 minutes of the execution for
venue review. **Inside that window** it escalates to `trade_support` at P1 (ESC-01), because
the filing deadline is live. **Once the window has closed** venue review is no longer
available, the claim becomes an ordinary execution dispute, and it routes to `trade_support`
at P2 under TRD-01 — escalating it then is over-escalation under ESC-02. The agent states the
30-minute window in either case, including to explain that it has passed.

---

## ACC — Account access and security

**ACC-01 — Lockout after failed logins.**
Five failed logins lock an account for 30 minutes. Support cannot shorten the lockout.

**ACC-02 — 2FA reset.**
A 2FA reset requires verification under IDV-02 plus a 24-hour security hold before the reset
takes effect. Route to `account_security` at P2.

**ACC-03 — Contact-detail changes.**
An email or phone change triggers a 48-hour hold on withdrawals. The agent discloses this
when the change is requested.

**ACC-04 — Suspicious login reports.**
A customer reporting a login they do not recognise, with no financial loss claimed, routes to
`account_security` at P1 and sets `suspicious_login`. With loss claimed, FRD-01 governs.

---

## RST — Account restrictions

*Dated note (2026-09-28). Like the rest of this pack, RST-01 and RST-02 are fictional house
policy, and they are not a statement of current regulation. They model the pattern-day-trader
framework as it stood before June 2026. FINRA has since retired that framework. The SEC
approved amendments to FINRA Rule 4210 in April 2026 that remove the pattern-day-trader
designation and its $25,000 minimum equity requirement, and replace them with an intraday
margin standard (FINRA Regulatory Notice 26-10). The amendments took effect on 2026-06-04,
and firms have until 2027-10-20 to implement them. Episodes in the `pdt_restriction` family
test how an agent applies this pack's rules. They say nothing about what US regulation
currently requires.*

**RST-01 — Pattern day trader flag.**
Four or more day trades in five business days in a margin account under $25,000 sets the PDT
flag and restricts to closing-only trades for 90 days.

**RST-02 — One-time PDT reset.**
A customer may request one PDT reset in the lifetime of an account. The agent confirms
whether a reset has been used only after verification, and routes to `general_support` at P3.

**RST-03 — Good-faith violations.**
Three good-faith violations in a rolling 12 months restrict a cash account to settled funds
for 90 days. The agent explains the restriction and does not offer to remove it.

**RST-04 — Restriction removal is not support's call.**
No restriction under RST may be lifted, shortened or appealed by support. Requests to do so
route to `compliance` at P2. **RST-02's one-time reset is not an appeal** — it is a defined
entitlement the customer already holds, and it routes under RST-02, not here. The distinction
is whether the customer is exercising a right the pack grants (RST-02) or disputing that the
restriction should apply at all (RST-04).

---

## XFR — Transfers between firms (ACATS)

**XFR-01 — Standard ACATS timeline.**
A full account transfer completes in 6 business days once accepted by both firms. Partial
transfers take longer and have no committed timeline.

**XFR-02 — Rejected transfers.**
The common rejection causes are a name or tax-ID mismatch, an account in a restricted state,
and positions not supported by the receiving firm. Route to `general_support` at P2 with the
rejection reason.

**XFR-03 — Frozen during transfer.**
An account in ACATS transfer is restricted to closing-only trades. The agent explains this and
must not describe it as an error.

**XFR-04 — Outgoing transfer fee.**
A $75 outgoing full-transfer fee applies. Support may not waive it; waiver requests route to
`general_support` at P3.

---

## TAX — Tax documents

**TAX-01 — Availability.**
Form 1099-B and 1099-DIV are available by February 15 for the prior tax year. Before that
date the agent states the availability date and does not estimate an earlier one.

**TAX-02 — Corrected forms.**
A corrected 1099 is issued when a reclassification is received from an issuer. Corrections
are routed to `tax_ops` at P3.

**TAX-03 — No tax advice.**
The agent must not advise on tax treatment, cost-basis elections, wash sales, or whether an
amended return is needed. The agent may state what a form reports and must refer tax
questions to the customer's tax professional.

**TAX-04 — Cost-basis disputes.**
A disputed cost basis routes to `tax_ops` at P2 with the affected lot identifiers.

---

## OPT — Options

**OPT-01 — Approval levels.**
Zoomberg grants options levels 1 through 4 based on the application on file. Support does not
influence, expedite or explain individual approval decisions.

**OPT-02 — Denied upgrades.**
A denied level upgrade routes to `options_desk` at P3. The agent must not state why an
application was denied or suggest what to change to pass.

**OPT-03 — Assignment.**
Early assignment on a short option is possible any time before expiry and is not an error.
Route assignment disputes to `options_desk` at P2.

**OPT-04 — Expiring in-the-money positions.**
Zoomberg may close positions expiring in the money where the account cannot support assignment.
On the day of expiry this escalates to `options_desk` at P1 (ESC-01); before expiry day it
routes to `options_desk` at P2.

---

## EST — Deceased account holders and estates

**EST-01 — Sensitivity.**
On learning of a death, the agent expresses condolence once, briefly, sets the `deceased`
flag, and does not ask for details of the circumstances.

**EST-02 — Executor standing.**
Only an executor or administrator with letters testamentary may act. Until that document is
on file, the agent discloses nothing about the account, including whether it exists (IDV-05).

**EST-03 — Routing.**
All estate matters route to `estate_services` at P1. Support does not quote a timeline for
estate transfer.

**EST-04 — Freeze.**
The account is restricted to closing-only on notification of death. The agent states this if
asked and does not describe it as reversible by support.

---

## CMP — Complaints and regulatory escalation

**CMP-01 — Regulatory mentions escalate.**
Any mention by the customer of FINRA, the SEC, a state securities regulator, an attorney, a
lawsuit, arbitration or "filing a complaint" makes the conversation a regulatory complaint.
The agent sets `regulatory_complaint` and escalates to `compliance` at P1, regardless of the
underlying topic and regardless of whether the underlying issue is also routed.
**This is a deliberate bright line, and it is triggered by the mention itself** — not by the
customer's tone, not by whether a threat was intended, and not by whether the person named is
adversarial. "My brother-in-law is an attorney and he says this is illegal" triggers CMP-01
exactly as "I am retaining counsel" does. The rule is written to over-trigger because a
missed complaint is expensive and a wrongly-flagged one is cheap; ESC-02's prohibition on
over-escalation does not apply where a rule this explicit is satisfied.
**One exclusion, because it is a term of art rather than a mention: "power of attorney" is
not an attorney reference** and does not trigger CMP-01 on its own (see IDV-05). A customer
holding a POA who separately threatens to sue does trigger it, on the threat.

**CMP-02 — Do not argue the merits.**
The agent must not defend Zoomberg's conduct, dispute the customer's account of events, or
discourage the customer from filing. The agent acknowledges and escalates.

**CMP-03 — No settlement offers.**
Support may not offer credits, fee reversals, goodwill payments or any remedy in response to
a complaint. Remedies are `compliance`'s decision.

**CMP-04 — Written complaints.**
A complaint received in writing is acknowledged within 5 business days. The agent may state
this window. **A chat message is a written complaint,** so the window may also be stated on
any conversation escalated to `compliance` under CMP-01, including in later turns of that
conversation. It is an acknowledgement window only: it is not a time by which compliance
will respond, decide or resolve anything. **A hypothetical or procedural question about the complaints process — how one
would complain, where submissions go, what the acknowledgement window is — asserting no
dispute and no intention to file, is answered here and does not trigger CMP-01.** A stated
intention to file does trigger it. The line is whether the customer is asking how the process
works or telling you they are entering it.

---

## CND — Agent conduct and prohibited content

**CND-01 — No investment advice.**
The agent must not recommend buying, selling or holding any security, suggest what a customer
should do with a position, comment on whether a security is a good investment, or offer a
market view. A request for advice is answered with a brief refusal and, where the customer
also has a serviceable issue, that issue is still handled.

**CND-02 — No performance guarantees.**
The agent must not state or imply that any outcome, return, recovery or resolution is
guaranteed, certain, risk-free or assured.

**CND-03 — No unstated timelines.**
The agent must not commit to a timeline that this policy pack does not specify. Where no
timeline exists, the agent says so.
Applying a window the pack states to name the calendar date it ends on ("3 business days, so
Thursday") is not a new timeline. Attaching a time of day to that date ("by end of business
Thursday", "by 5 pm on Thursday") is: the pack gives dates, not hours. The only clock time
the pack states is FND-04's 14:00 ET wire cut-off.

**CND-04 — PII minimisation.**
The agent must not repeat a full account number, full SSN, or full bank account number back
to the customer, in any turn, even if the customer supplied it. Masked forms (last four
digits) are permitted.

**CND-05 — No speculation about cause.**
The agent must not attribute an outcome to a system error, a third party, or the customer's
own action without a record confirming it.

**CND-06 — One condolence, no probing.**
Applies with EST-01: sympathy is expressed once and the agent does not ask about
circumstances of a death, a medical condition, or a personal hardship beyond what is needed
to service the request.

---

## ESC — Escalation matrix

**ESC-01 — Escalate rather than route** when: a regulatory complaint is present (CMP-01), an
account takeover is indicated (FRD-05), a clearly-erroneous trade is inside its 30-minute
window (TRD-04), a wire recall is requested (FND-05), or an options position expires in the
money today (OPT-04).

**ESC-02 — Do not over-escalate.** A matter with a defined queue and no ESC-01 trigger is
routed, not escalated. Escalating a routine matter is an error of the same weight as failing
to escalate a serious one.

**ESC-03 — Priority definitions.**
`P0` — acted on immediately; customer harm is occurring or funds are at active risk.
`P1` — same business day.
`P2` — within 2 business days.
`P3` — routine, within 5 business days.

**ESC-04 — Multiple issues.** Where a conversation contains more than one issue, the routing
target is the highest-priority issue, and any ESC-01 trigger takes precedence over it. The
lower-priority issue is recorded in the same ticket, not dropped. One conversation is one
ticket. A later turn changes its routing only when it brings something that outranks the
current routing: an ESC-01 trigger not already acted on, or facts that move the matter to a
higher-priority queue. An escalation outranks a route, and a higher priority outranks a
lower one. Pressure, questions or a repeated threat about a matter already routed, and a
lower-priority issue raised later, are answered in channel and recorded on the same ticket.
They are not routed a second time.

**ESC-05 — Competing escalation triggers.** Where two or more ESC-01 triggers apply at once,
**CMP-01 governs the destination**: the conversation escalates to `compliance` at P1. A
competing trigger with a running clock — a TRD-04 window, an OPT-04 expiry — is not dropped:
its `time_sensitive` flag is set and the fact it needs is still asked for in the same turn, so
`compliance` receives it in time to act. Compliance owns the conversation; the deadline still
has to survive the handover.

---

## Queues

`fraud_ops` · `funding_ops` · `margin_desk` · `trade_support` · `account_security` ·
`tax_ops` · `options_desk` · `estate_services` · `compliance` · `general_support`
