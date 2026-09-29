# Authoring brief: slice <N>

You are writing labelled support conversations for <Company>'s triage model. Read these
first, in order: `policies.md` (the only ground truth), the schema and flag definitions in
`supportrl.yaml` and `prompt.md`, and the three gold episodes in `data/train.jsonl`
(ids <...>).

**Your slice**

| | |
|---|---|
| families | <family_a>, <family_b> |
| ids | `<PREFIX>-TRAIN-0N00..0N09`, `<PREFIX>-DEV-0N00..0N02`, `<PREFIX>-TEST-0N00..0N05` |
| per split | train <k>, dev <k>, test <k> |
| difficulty mix | standard / hard / trap: <a / b / c> (test skews harder) |
| verification | at least <x>% of episodes open unverified, including the shapes: verification not needed at all; protection proceeding unverified; a third party with no standing; two failed attempts; half answerable, half gated |

**Rules**

1. Every label must rest on a policy you can cite. If you cannot decide a label from the pack
   alone, **do not guess**: record it as a doubt (rule 5).
2. Follow-up customer turns must make sense after any reasonable agent reply.
3. A follow-up about a matter already routed is `resolve` unless the new turn outranks the
   standing ticket.
4. Invented numbers must be invalid by construction (never-issued SSN ranges, account numbers
   that fail checksums, last four matching `context`). No real people.
5. Run `supportrl validate <project> --split <split>` until it passes, then hand in your slice
   **with a list of the episodes you are least confident about and why.** This list is the
   most useful thing you will produce. A doubt about a label is usually a gap in the rules.
