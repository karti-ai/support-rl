# Review checklist (after merging slices)

**Mechanical**
- [ ] `supportrl validate` passes; every warning read and either fixed or explained
- [ ] `supportrl probes` run on the current detectors
- [ ] every author's least-confident list triaged: rule defect, label defect, or fine

**Coverage (read across slices, not within them)**
- [ ] every family appears in test; test is harder than train
- [ ] each hard criterion is live in a meaningful share of test decisions (count them: the
      worked example once had its verification gate live in 3 of 24 test episodes)
- [ ] every action type, and every flag, appears in train and in test
- [ ] traps exist for each easy mistake: over-escalation bait, advice inside a real request,
      a customer asserting a wrong timeline, an apparent fraud that is a misunderstanding

**Consistency**
- [ ] sort decisions by (action type, flags, family) and read neighbours side by side: the same
      situation is labelled the same way everywhere
- [ ] follow-up decisions follow the outrank rule
- [ ] required citations are still the on-point rule after every pack change (re-audit)
- [ ] no near-duplicate scenarios across splits, even reworded

**Hygiene**
- [ ] no valid-looking SSNs, routing or card numbers; masked last four consistent
- [ ] no real person; no real company next to an allegation
- [ ] dates, weekdays and time zones agree with `context`

**Record**
- [ ] every defect and its fix is written in the review log, including your own mistakes
- [ ] the dev partition and the selection rule are fixed before any model output on dev is seen
