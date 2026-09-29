# env: a verifiers environment for any support-rl project

`supportrl_env.load_environment` wraps the evaluator and the scripted customer in a
[verifiers](https://github.com/PrimeIntellect-ai/verifiers) `MultiTurnEnv`:

- **system**: your `prompt.md` followed by your policy pack
- **first user message**: the rendered session context and the customer's first turn
- after each assistant turn, the next scripted customer turn is injected; the rollout stops
  when every decision point has a response
- **reward** (weight 1): the supportrl episode score. Zero-weight metrics for the dashboard:
  `format_invalid_rate`, `hard_fail`, `graded_mean`, `comp_*`, `hard_<code>`,
  over/under-escalation, under-route, missed/over-ask, `missing_decisions`,
  `max_completion_tokens`, `truncated_turns` and `thinking_turns` (must stay 0 with thinking off)
- **never model input**: episode ids, family, difficulty, split, labels, rationales

```python
from supportrl_env import load_environment

env = load_environment(project="examples/zoomberg", split="train", repeats=8, shuffle_seed=0)
```

| argument | meaning |
|---|---|
| `project` | path to a project; default: the project bundled into a built package |
| `split` | any split or subset in `supportrl.yaml` (`train`, `dev`, `dev_val`, `test`, ...) |
| `allow_locked` | required to load a locked split: the approved final evaluation only |
| `advisory_hard` | hard criteria reported but not zeroing (exact criteria refuse) |
| `scoring` | a named scoring variant, e.g. `"v5"` |
| `repeats`, `shuffle_seed` | train only: N shuffled passes, so a hosted sampler that reads tasks in order neither runs out nor sees one family per batch |
| `max_episodes` | first N by id, for smoke runs |

It targets the classic `vf.MultiTurnEnv` / `load_environment` API, which is the same in
verifiers 0.2.x and 0.3.x. A hosted trainer runs its own verifiers build, so the built
package requires `verifiers>=0.2.0` and never pins it: pinning downgrades the trainer's own
install. The dataset has no `task` column, because newer verifiers read `task` as a
serialized task payload and reject a plain string.

## Self-contained package for hosted training

```bash
pip install -e ".[env]"
supportrl env build examples/zoomberg --out build/zoomberg-env
pip install -e build/zoomberg-env                        # local use
vf-eval zoomberg-support-triage -a '{"split": "dev_val"}' -m <model> -b <base_url> -k <KEY_ENV> \
    -n -1 -r 1 -T 0 -t 1024 -S '{"chat_template_kwargs": {"enable_thinking": false}}'
prime env push --path build/zoomberg-env --visibility PRIVATE   # hosted
```

The package vendors `supportrl` and `supportrl_env` and bundles your project (config,
policy pack, prompt, probes, plugins and split files). **Locked splits are left out by
default** (`--include-locked` to override): hosted training needs train and the selection
subset, and your test set never has to leave your machine.

`supportrl eval PROJECT --replay <vf-eval output dir>` re-scores vf-eval results directly.

## Checking the transport before you pay for it

Before a hosted run, point `vf-eval` (or `supportrl baseline`) at a mock or cheap endpoint
and check what is actually sent: `chat_template_kwargs.enable_thinking=false` at the top
level of the request, the temperature and token budget you intended, one request per
decision point. `tests/test_cli.py` does this against a mock server. Verify what is emitted,
not what is configured: some providers serve thinking models with thinking **on** by default,
and a turn that thinks silently eats the token budget and fails the format gate.
