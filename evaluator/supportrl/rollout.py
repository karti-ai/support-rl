"""Scripted rollouts: replay an episode's customer turns against a model.

The customer's follow-ups are fixed text. They do not react to what the model said, so a
rollout is deterministic given the model's outputs and an eval is reproducible. The model's
own earlier replies stay in the conversation history (it is on-policy), exactly as in the
hosted training environment.

``generate`` is any callable ``messages -> Completion`` (see ``client.ChatClient.chat``), so
the same loop drives an HTTP endpoint, a local ``transformers`` model or a test double.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .client import Completion
from .data import first_user_message, followups
from .pack import Pack

Generate = Callable[[list[dict]], Completion]


def messages_for(pack: Pack, episode: dict) -> list[dict]:
    """The opening messages: system (instructions + policy pack), then the first user turn."""
    return [
        {"role": "system", "content": pack.system_prompt()},
        {"role": "user", "content": first_user_message(pack, episode)},
    ]


def run_episode(pack: Pack, episode: dict, generate: Generate) -> dict:
    msgs = messages_for(pack, episode)
    script = followups(episode)
    n = len(episode["decisions"])
    responses, usage, error = [], [], None
    for k in range(n):
        try:
            c = generate(list(msgs))
        except Exception as exc:  # a failed call is recorded, never retried silently here
            error = f"{type(exc).__name__}: {exc}"
            break
        responses.append(c.text)
        usage.append(c.usage)
        msgs.append({"role": "assistant", "content": c.text})
        if k < n - 1:
            msgs.append({"role": "user", "content": script[k]})
    return {"episode_id": episode["id"], "responses": responses, "usage": usage, "error": error}


def run_many(
    pack: Pack, episodes: list[dict], generate: Generate, concurrency: int = 8, progress=None
) -> list[dict]:
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        for i, row in enumerate(pool.map(lambda e: run_episode(pack, e, generate), episodes), 1):
            out.append(row)
            if progress:
                progress(i, len(episodes), row)
    return out
