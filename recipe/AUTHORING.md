# Authoring guide

How to write ~100 labelled conversations with several authors (people, LLM agents, or both)
and end up with ground truth rather than a pile of defensible-but-arguable labels. These
practices come from building the worked example, whose full record is
[`examples/zoomberg/docs/REVIEW-LOG.md`](../examples/zoomberg/docs/REVIEW-LOG.md): 23 entries,
most of them defects in the *rules*, found by the process below.

## Before anyone writes an episode

1. **Write the policy pack, the schema and the vocab definitions** (recipe/README.md, steps
   1–3). Define every term, including the ones that feel obvious. In the worked example both
   schema gaps were terms that felt self-explanatory: nine flags that nobody had defined, and
   a `resolve` action that was in the vocabulary with no meaning.
2. **Write the validator configuration first** (`label_rules`, `follow_up_rule`, context
   schema) and run it on the three gold examples. The validator is what lets authors work in
   parallel without drifting: it checks structure, vocabularies, policy IDs, internal
   consistency and the rules the pack states unconditionally.
3. **Write three gold episodes yourself** — one standard, one hard, one trap — with full
   rationales. They set the quality bar ([`templates/authoring-brief.md`](templates/authoring-brief.md)
   tells authors to read them). Do not let every author copy their shape (see 6).

## Split the work into disjoint slices

Give each author a **disjoint slice**: a set of families, with target counts per split and
per difficulty, and an id range. Disjoint slices keep authors from writing near-duplicates of
each other, make leakage between train and test less likely, and make it obvious who owns a
defect. The brief is in [`templates/authoring-brief.md`](templates/authoring-brief.md).

## Require every author to report their least-confident cases

This is the most valuable instruction in the process. Every author ends with a list: *the
episodes I am least sure are labelled correctly, and why*.

In the worked example **every reported doubt turned out to be a real defect, and almost every
one was a defect in the ground truth, not in the episode**: two rules that contradicted each
other, a carve-out list read as exhaustive, a bright-line rule that accidentally caught "power
of attorney", a rule with no route for a legitimate customer. Sixteen of the eighteen defects in
the first two passes were found this way. None were caught by the validator, because a
validator can only check what someone already knew to specify.

## Fix the rule, not the case

When a doubt is real, find the rule that let two readings exist and fix **the rule** (the
pack, the schema, the flag table, the scorer), then relabel every episode it touches. Patch
only the episode and the ambiguity is still there for the next author to rediscover. In the
worked example 15 of the first 18 fixes went into the rules. The exception is when the rule is
fine and the label is wrong; then fix the label.

## Re-audit whenever ground truth moves

A rule that changes after authoring can silently invalidate labels built on it: a required
citation that was right when written and is stale now. Nothing automatic catches that except
a re-audit. Add a `label_rule` for the new rule whenever it can be stated mechanically, so the
validator finds every stale label at once.

## Run a cross-slice audit

After merging, one reviewer reads **across** slices, not within them. It catches what no
single author can see:

- **Coverage gaps.** In the worked example the verification gate (a hard criterion) was live
  in only 3 of 24 test episodes, because each slice looked reasonable on its own and authors
  had been told not to copy the gold example's ask-verification shape. It took a dedicated
  gap-fill pass, with the missing shapes enumerated in advance.
- **The same situation labelled two ways** in two slices. Sort decisions by
  (action type, flags, family) and read neighbours side by side.
- **Near-duplicates across splits.** The validator catches identical openings; a person
  catches the same scenario reworded.

The checklist is [`templates/review-checklist.md`](templates/review-checklist.md). Record every
defect found and what was changed in a review log; a log that only lists other people's
mistakes is not a review log.

## Data hygiene

- Invented numbers must be invalid by construction: SSNs in never-issued ranges (area 9xx),
  account numbers that fail the ABA routing checksum, last-four consistent with the masked
  account in `context`. The validator warns on long digit runs so each one gets looked at.
- No real person, and no real company next to an allegation. Fictional firm names; real
  tickers only in neutral contexts.
- Dates and weekdays must agree (the scorer and the model both do date arithmetic from
  `context.local_time`).
- Keep a clear line between what the pack says is house policy and what is real regulation,
  and date it.

## Candidate episodes from the LLM customer

`supportrl simulate` produces unlabelled candidates. Treat them as drafts from one more
author: label them against the pack, run them through the same review, and never put
candidates generated by talking to the model under evaluation into its test split.
