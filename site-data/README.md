# site-data: replayable eval results for the demo site

`export.py` turns saved eval outputs into one JSON file per (project, split) that a static
site can replay: every conversation, the label for every decision, and for every model its
raw output, parsed reply and action, component scores, hard-criterion hits and gates. No
model is called; all scores are recomputed from the saved outputs with the project's scoring
config, so the numbers match `supportrl report` exactly. The output is deterministic: re-running
the export on the same runs produces the same bytes.

```bash
pip install -e .
python site-data/export.py site-data/zoomberg.yaml     # -> site-data/out/zoomberg-{test,dev}.json
```

Adding a model (v2): run it once on the split (`supportrl eval examples/zoomberg --model ...
--split test --allow-locked`), commit the run directory under
`examples/zoomberg/results/test/`, add a `runs:` entry in `zoomberg.yaml`, re-run the export.
To show a different scoring variant, add `scoring: v5` to an export.

**License.** The JSON in `out/` embeds the Zoomberg episodes, labels, policy titles and model
outputs. It is **not** covered by the repository's Apache-2.0 license: it is CC-BY-4.0
([license](https://creativecommons.org/licenses/by/4.0/)), attribution Karti Tripathi —
[KartiOS/fintech-support-triage](https://huggingface.co/datasets/KartiOS/fintech-support-triage).
A site that displays it must show that attribution. Details:
[`examples/zoomberg/DATA-LICENSE.md`](../examples/zoomberg/DATA-LICENSE.md).

## Schema `supportrl-site-data/1`

```jsonc
{
  "schema": "supportrl-site-data/1",
  "project": {
    "name": "zoomberg", "title": "Zoomberg Brokerage support triage",
    "scoring": "fst-scorer-v4",            // the scoring config every number below was computed with
    "prompt_version": "fst-prompt-v1",
    "policy_pack_sha256": "081b01ae..."
  },
  "split": "test",
  "data_license": {"name": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
                   "attribution": "Karti Tripathi — KartiOS/fintech-support-triage",
                   "source": "https://huggingface.co/datasets/..."},   // show the attribution
  "weights": {"action_type": 0.15, "destination": 0.25, "priority": 0.15,
              "flags": 0.15, "policy_citation": 0.2, "must_ask": 0.1},
  "hard_criteria": [                        // in display order
    {"code": "H1_disclosure_before_verification", "short": "H1",
     "description": "IDV-01 -- an account-specific fact stated before verification",
     "kind": "detector"},                  // "detector" (text heuristic, has error bars) | "exact"
    ...
  ],
  "policies": {"IDV-01": "Verification precedes account-specific disclosure", ...},  // id -> title
  "models": [                               // display order; `key` is used everywhere below
    {"key": "v1", "label": "Karti-Small-Support-9B v1", "description": "...",
     "model": "...", "sampling": {"temperature": 0.0, "max_tokens": 1024, "chat_template_kwargs": {...}},
     "summary": {
       "episodes": 32, "decisions": 53,
       "composite": 0.706,                  // headline: mean episode reward, hard criteria zeroing
       "composite_advisory": 0.738,         // with `advisory` detectors demoted (null if none)
       "advisory": ["H1", "H4"],
       "composite_no_hard_gate": 0.738,
       "episodes_hard_failed": 1,
       "components": {"action_type": 0.679, ...},       // means over decisions
       "hard_violations": {"H1": 1, "H2": 0, ...},      // decisions with a hit, by short code
       "gates": {},                                     // decision gates fired, by name
       "format_invalid": 0,
       "over_escalation_rate": 0.0, "under_escalation_rate": 0.038,
       "under_route_rate": 0.094, "missed_ask_rate": 0.132,
       "action_type_correct": {"resolve": "17/19", ...},  // by label action type
       "by_difficulty": {"hard": 0.724, ...}, "by_family": {...}
     }}
  ],
  "episodes": [
    {
      "id": "TST-EVAL-0100", "family": "account_access", "difficulty": "standard",
      "context": {"verified": false, "account_masked": "****5520", ...},   // what the model was told
      "turns": [                            // the conversation; agent turns have text null
        {"t": 0, "role": "customer", "text": "...", "decision_point": null},
        {"t": 1, "role": "agent", "text": null, "decision_point": "d1"}
      ],
      "decisions": [
        {
          "decision_point": "d1",
          "target": {                       // the label (answer key)
            "action_type": "route", "queue": "account_security", "escalate_to": null, "priority": "P1",
            "required_flags": [...], "forbidden_flags": [...],
            "must_cite": [...], "may_cite": [...],
            "must_ask": [...], "prohibited": [...], "allowed_timeline_claims": [...],
            "may_disclose_account_details": false,     // every boolean label field is copied
            "rationale": "..."
          },
          "models": {
            "v1": {
              "raw": "{\"reply\": ...}",    // exactly what the model returned
              "format_valid": true, "format_error": null,   // e.g. "not_json", "bad_queue:..."
              "reply": "...",               // null when the format gate failed
              "action": {"type": "route", "queue": "...", "escalate_to": null, "priority": "P1",
                         "flags": [...], "policy_ids": [...]},   // null when the gate failed
              "components": {"action_type": 1.0, "destination": 1.0, ...},
              "graded": 1.0,                // weighted sum before gates
              "score": 1.0,                 // after hard criteria and decision gates
              "hard_hits": [{"code": "...", "short": "H1", "evidence": ["rule: excerpt"], "zeroing": true}],
              "gates": []
            }
          }
        }
      ],
      "results": {"v1": {"reward": 1.0, "hard_failed": false}}   // episode reward per model
    }
  ]
}
```

Notes for the site:

- A hard hit with `zeroing: true` zeroes the **whole episode** (`results.<key>.reward` is 0),
  not just that decision. Show it at the decision where it happened.
- `H1` and `H4` are text detectors with measured recall below 0.9 on holdout probes; the one
  v1 hard hit on test (EVAL-0600, H1) is a known false positive. Label detector hits as
  "flagged by detector", not as ground truth.
- A model can be missing from a decision's `models` if its run did not cover that episode.
- `decisions[i]` lines up with the i-th agent turn in `turns`.
- Files are UTF-8 JSON, about 400 KB for the test split with three models.
