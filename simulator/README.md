# simulator: scripted and LLM customers

## 1. Scripted customer (eval and training)

The customer's turns are written in the episode and replayed in order, whatever the model
says. The model's own earlier replies stay in its history, so the rollout is on-policy for
the model, deterministic for the customer, and reproducible. `supportrl baseline`, `eval`,
the verifiers environment and both training backends all use it
(`supportrl_sim.scripted.ScriptedCustomer`, `supportrl.rollout.run_episode`).

The trade-off is deliberate. A customer that reacts to the model makes every rollout a
different conversation, so rewards stop being comparable across a GRPO group and an eval
stops being repeatable. Scripted follow-ups are written as the customer's plausible next
message; label them for what the customer says, not for what an ideal agent would have
said just before.

## 2. LLM customer (new candidate data, play-testing)

An OpenAI-compatible model plays the customer from a persona and a goal, and reacts to what
the agent actually says. It is **never in the reward path.** It has two uses.

### Generate candidate episodes

```bash
supportrl simulate examples/zoomberg --personas simulator/personas.example.yaml --n 2 \
    --customer-model <model> --customer-base-url <url> --customer-api-key-env KEY \
    --model <agent model> --base-url <url> --api-key-env KEY \
    --out candidates/new.jsonl
```

For each persona the customer opens, the agent answers under the project's real system
prompt, the customer reacts, and so on up to the persona's `turns` (and the project's
`max_decisions`). Output rows have the episode shape with:

- the customer turns fixed (they become the scripted turns once accepted),
- agent turns as empty decision points,
- `decisions: []` — **no labels**,
- `review: {status: unreviewed, persona, customer_model, agent_replies, ...}`.

`agent_replies` are kept for the reviewer's reference only. They are not labels: a
generated conversation is only as good as the reviewer who labels it against the pack.

Every loader skips `unreviewed` rows, so a candidate cannot reach training or evaluation by
accident. To accept one: write its `decisions` against the policy pack (see
`recipe/AUTHORING.md`), set `review.status: reviewed`, give it an id in your id scheme, move it
into a split file, and run `supportrl validate`. `supportrl validate PROJECT --candidates
FILE` structure-checks the raw candidates.

Two cautions. The customer's later turns reacted to one particular agent reply; when you
accept the episode they become fixed, so read them as a script and reject any that only make
sense after that exact reply. And never add candidates to the test split that were generated
by talking to the model you will evaluate on it.

### Play-test a model

```bash
supportrl play examples/zoomberg --model support --base-url http://localhost:8000/v1 \
    --context '{"verified": false, "account_masked": "****1234", "account_type": "margin",
                "account_age_days": 400, "local_time_et": "2026-05-12T09:40:00-04:00"}'
```

You type the customer's messages (an empty line ends the chat), or pass `--customer-model`
with `--persona` and `--goal` to let an LLM play the customer. Each agent turn shows the
reply, the parsed action, format failures, and any detector that would fire. Without labels
there is no score: the disclosure check assumes the caller is unverified unless the context
says otherwise, and the timeline check treats every commitment as unstated.

## Personas file

```yaml
- id: wire-recall-curt               # used in candidate ids
  family: wire_recall                # optional, copied to the candidate
  difficulty: hard                   # optional
  turns: 2                           # decision points to generate (1..max_decisions)
  persona: A curt small-business owner who types in short bursts.
  goal: Get this morning's wire recalled. Mentions a lawyer if stonewalled.
  context: {verified: false, account_masked: "****5520", account_type: cash,
            account_age_days: 1200, local_time_et: "2026-06-03T10:05:00-04:00"}
```

`context` must satisfy your `episodes.context` schema; it is rendered into the agent's first
message exactly as in the real episodes. See `personas.example.yaml`.
