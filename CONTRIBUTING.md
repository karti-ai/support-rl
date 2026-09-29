# Contributing

Thanks for helping. Issues and pull requests are welcome at
https://github.com/karti-ai/support-rl.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # add "verifiers==0.2.0" "mcp<2" to run tests/test_env.py
pytest -q
ruff check . && ruff format --check .
```

The whole suite runs offline in well under a minute. Nothing in CI needs a secret or a GPU.

## Ground rules

- **Scoring changes are versioned.** `tests/test_zoomberg_regression.py` pins every published
  Zoomberg number. If your change moves one, it is a scoring change: add it as a scoring
  variant (or a new detector option) instead of changing the default, and say in the PR what
  it does to the frozen results (`supportrl eval examples/zoomberg --replay ... --scoring <new>`).
- **Detector changes come with probes.** Add dev probes for what you fixed. Never edit a
  holdout probe set to make a detector pass; write a new versioned holdout
  (`<code>.holdout-v2.jsonl`) before running the detector on it, and quote its first
  measurement.
- **Never add a result you did not observe.** Frozen runs in `examples/*/results/` are model
  outputs as produced. Regressions stay in the record.
- **No secrets in run records.** Endpoints take `--api-key-env NAME`; keys are never written.
- **Data must be fictional and clean.** No real people, no real account/SSN/routing numbers
  (use never-issued or checksum-failing values), no real company next to an allegation. Say
  who or what authored new data (people, LLM agents, both) in the PR.

## Adding an example project

A new domain under `examples/<name>/` is very welcome. It needs a `supportrl.yaml`, a policy
pack, data that passes `supportrl validate` with no errors, probe sets for every detector
it uses, and a README that states its limits. Frozen baselines are a bonus.

## License

Code is Apache-2.0: by contributing code you agree to license it under Apache-2.0.

The Zoomberg example data (`examples/zoomberg/`, exported to `site-data/out/`) is CC-BY-4.0,
attribution Karti Tripathi — KartiOS/fintech-support-triage, and is not covered by the
Apache-2.0 license; see `examples/zoomberg/DATA-LICENSE.md`. Changes to those files are
contributed under CC-BY-4.0. A new example project must ship its own data license file
stating the terms of its data.
