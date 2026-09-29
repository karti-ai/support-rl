# Data license (Zoomberg example)

This file is the single place that states the license of the Zoomberg example data. Code in
this repository is Apache-2.0 ([LICENSE](../../LICENSE)); the files listed below are **not**
covered by the Apache-2.0 license.

**License:** [Creative Commons Attribution 4.0 International (CC-BY-4.0)](https://creativecommons.org/licenses/by/4.0/)

**Attribution:** Karti Tripathi — [KartiOS/fintech-support-triage](https://huggingface.co/datasets/KartiOS/fintech-support-triage)

**Source:** the Hugging Face dataset `KartiOS/fintech-support-triage`, revision
`6469529a20f9b8420534ba1ab42cd89a6f2e20b6`.

## Covered files

| path | relation to the source |
|---|---|
| `examples/zoomberg/data/*.jsonl` | byte-identical to the dataset's `data/*.jsonl` (`scripts/fetch_from_hf.py --check`) |
| `examples/zoomberg/policies.md` | byte-identical to the dataset's `policies/policies.md` |
| `examples/zoomberg/docs/*.md` | adapted from the dataset's `docs/`. Changes: hard-criterion wording now says a violation zeroes the whole episode; one sentence about the base model reworded; one order-ID prefix described as a placeholder |
| `examples/zoomberg/probes/*` | detector probe sets written for this dataset |
| `examples/zoomberg/results/**` | model outputs on this data (Qwen/Qwen3.5-4B, Qwen/Qwen3.5-9B and adapters trained from Qwen/Qwen3.5-9B), with scores computed by this repository |
| `site-data/out/*.json` | exports of the above: every episode, the labels, the policy titles and the model outputs |

`examples/zoomberg/prompt.md` is not covered here: followed by `policies.md` it is
byte-identical to `prompt/system_prompt.txt` in the model repository
[KartiOS/Karti-Small-Support-9B](https://huggingface.co/KartiOS/Karti-Small-Support-9B)
(Apache-2.0), and it is covered by this repository's Apache-2.0 license.

## Notice

Zoomberg Brokerage is fictional and not affiliated with any real company. All customers,
accounts and events are invented. Nothing here is legal, regulatory, tax or financial advice.
