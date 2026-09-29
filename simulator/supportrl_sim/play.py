"""Interactive play-test: you (or an LLM customer) chat with a model under the real prompt.

    supportrl play examples/zoomberg --model support --base-url http://localhost:8000/v1 \
        --context '{"verified": false, "account_masked": "****1234", "account_type": "margin",
                    "account_age_days": 400, "local_time_et": "2026-05-12T09:40:00-04:00"}'

Each agent turn prints the reply, the parsed action and whether it passed the output
contract, plus any detector that fires. With no labels there is no score: the detectors
are hints (the disclosure check assumes the caller is unverified unless the context says
``verified: true``; the timeline check treats every commitment as unstated).
"""

from __future__ import annotations

import json
from collections.abc import Callable

from supportrl.contract import parse
from supportrl.detectors import DetectorInput
from supportrl.pack import Pack
from supportrl.rollout import Generate
from supportrl.scorer import Scorer


def describe_turn(pack: Pack, scorer: Scorer, raw: str, customer: list[str], context: dict) -> str:
    p = parse(raw, pack)
    if not p.ok:
        return f"  [FORMAT FAIL: {p.error} {p.diagnostics}]\n  raw: {raw[:500]}"
    a = p.output.action
    lines = [f"  agent: {p.output.reply}", f"  action: {json.dumps(a.to_dict())}"]
    target = {"allowed_timeline_claims": []}
    for h in pack.hard_criteria:
        if h.detector is None:
            continue
        if h.when.get("target_false") and context.get("verified"):
            continue
        hits = scorer.detector(h.code).detect(DetectorInput(p.output.reply, customer, context, target))
        if hits:
            lines.append(f"  ! {h.short} would fire: {'; '.join(str(x) for x in hits)[:200]}")
    return "\n".join(lines)


def play(
    pack: Pack, agent: Generate, context: dict, read_customer: Callable[[], str | None], out=print
) -> list[dict]:
    scorer = Scorer(pack)
    msgs = [{"role": "system", "content": pack.system_prompt()}]
    customer: list[str] = []
    while True:
        text = read_customer()
        if not text:
            break
        customer.append(text)
        content = (pack.render_context(context) + pack.customer_header + text) if len(customer) == 1 else text
        msgs.append({"role": "user", "content": content})
        raw = agent(list(msgs)).text
        msgs.append({"role": "assistant", "content": raw})
        out(describe_turn(pack, scorer, raw, customer, context))
    return msgs
