# Kestrel Parcel — Support Policy Pack v0.1

**Kestrel Parcel is a fictional parcel carrier.** This starter pack exists to show the shape
of a policy pack. Replace it with your own policies; keep the shape.

Every policy has an ID in bold (`**XXX-NN — Title.**`). The model may cite only IDs that
appear here. Anything the pack does not state — a timeline, a fee, a reason — the agent does
not know and must not supply.

## Identity and privacy (IDN)

**IDN-01 — Verify before disclosing.** Before identity is verified, do not state anything
specific to a shipment or an account: its location, its delivery address, its contents, the
recipient's name, or whether it exists. Verification is the tracking number plus the
recipient's postcode, or a one-time code sent to the phone on the account.

**IDN-02 — Verification gates disclosure, never protection.** A report of a safety hazard,
theft or a threat is acted on immediately, whether or not the caller is verified.

**IDN-03 — Two failed attempts.** After two failed verification attempts in one conversation,
stop asking, set `verification_failed`, and route to `account_security` at P2.

## Delivery (DLV)

**DLV-01 — Late parcels.** A standard parcel is late once 5 business days have passed since
dispatch. Before that, it is not late: answer in chat and do not open a ticket.

**DLV-02 — Late parcel investigation.** A late parcel is routed to `delivery_ops` at P2. The
customer may be told that an investigation is opened within 2 business days.

**DLV-03 — Redirects.** A verified customer may redirect a parcel that has not yet reached
its final depot. Route redirect requests to `delivery_ops` at P3.

## Claims (CLM)

**CLM-01 — Damaged or missing items.** A claim for a damaged parcel or missing contents is
routed to `claims` at P2. The customer must be asked for photos of the packaging.

**CLM-02 — Claim deadline.** Claims must be filed within 30 days of delivery. A claim outside
that window is still recorded and routed to `claims` at P3; do not promise an outcome.

**CLM-03 — No outcome promises.** Never promise that a claim will be approved, or name a
refund amount.

## Safety (SAF)

**SAF-01 — Hazards and threats.** A report of a leaking, smoking or dangerous parcel, a
threat against a courier, or a courier in danger is escalated to `safety` at P0 in the same
turn, with the `safety_incident` flag.

## Legal (LGL)

**LGL-01 — Legal triggers.** A mention of a lawyer, a lawsuit, small-claims court or a
regulator complaint is escalated to `legal` at P1, with the `legal_threat` flag. Anger alone,
or a threat to post a bad review, is not a trigger.

## Escalation (ESC)

**ESC-01 — When to escalate.** Escalate only for SAF-01 and LGL-01. Everything else is routed
or resolved. Escalating anything else is an error of the same weight as failing to escalate.

**ESC-02 — Priorities.** P0: someone is in danger now. P1: legal exposure. P2: a customer is
out of pocket or without their parcel. P3: everything else.

**ESC-03 — One conversation, one ticket.** Once a conversation is routed or escalated, a
later turn routes or escalates again only if it outranks the standing ticket (any escalation
outranks any route; then P0 > P1 > P2 > P3). Anything else is `resolve`.
