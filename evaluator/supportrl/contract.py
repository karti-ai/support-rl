"""Stage 1: the output contract (format gate).

At each decision point the model must answer with exactly one JSON object and nothing else::

    {"reply": "<text the customer sees>",
     "action": {"type": ..., "queue": ..., "escalate_to": ..., "priority": ...,
                "flags": [...], "policy_ids": [...]}}

The whole response is parsed as-is. There is no "find the JSON somewhere in the text"
fallback: a lenient parser ends up scoring text the model never committed to, and it hides
format regressions behind policy scores. A Markdown fence, a preamble, a ``<think>`` block,
trailing text or a duplicate key all fail the gate. Why it failed is recorded as a
diagnostic, and a diagnostic never rescues a response.

Structural inconsistency (a queue on a ``resolve``) is *not* a format failure. The
``destination`` component scores it, so it stays measurable on its own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .pack import Pack

ACTION_KEYS = ("type", "queue", "escalate_to", "priority", "flags", "policy_ids")
_FENCED = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True)
class Action:
    type: str
    queue: str | None
    escalate_to: str | None
    priority: str | None
    flags: tuple[str, ...]
    policy_ids: tuple[str, ...]

    @property
    def destination(self) -> str | None:
        return self.escalate_to if self.type == "escalate" else self.queue

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "queue": self.queue,
            "escalate_to": self.escalate_to,
            "priority": self.priority,
            "flags": list(self.flags),
            "policy_ids": list(self.policy_ids),
        }


@dataclass(frozen=True)
class Output:
    reply: str
    action: Action


@dataclass(frozen=True)
class Parsed:
    ok: bool
    output: Output | None = None
    error: str | None = None
    diagnostics: dict = field(default_factory=dict)


class _Dup(ValueError):
    pass


def _strict_object(pairs):
    out: dict = {}
    for k, v in pairs:
        if k in out:
            raise _Dup(k)
        out[k] = v
    return out


def _decode(text: str):
    return json.loads(text, object_pairs_hook=_strict_object)


def _diagnostics(text: str) -> dict:
    diag = {}
    if "<think>" in text or "</think>" in text:
        diag["think_tag"] = True
    m = _FENCED.match(text)
    if m:
        try:
            _decode(m.group(1))
            diag["fenced_json"] = True
        except ValueError:
            pass
    return diag


def check_object(obj, pack: Pack) -> Parsed:
    """Validate an already-decoded object against the contract and the pack's vocabularies."""
    if not isinstance(obj, dict):
        return Parsed(False, error="not_an_object")
    if set(obj) != {"reply", "action"}:
        return Parsed(False, error=f"top_level_keys:{sorted(obj)}")
    reply, action = obj["reply"], obj["action"]
    if not isinstance(reply, str) or not reply.strip():
        return Parsed(False, error="reply_not_nonempty_string")
    if not isinstance(action, dict):
        return Parsed(False, error="action_not_object")
    if set(action) != set(ACTION_KEYS):
        return Parsed(False, error=f"action_keys:{sorted(action)}")
    if action["type"] not in pack.action_types:
        return Parsed(False, error=f"bad_type:{action['type']!r}")
    for key in ("queue", "escalate_to"):
        if action[key] is not None and action[key] not in pack.queues:
            return Parsed(False, error=f"bad_{key}:{action[key]!r}")
    if action["priority"] is not None and action["priority"] not in pack.priorities:
        return Parsed(False, error=f"bad_priority:{action['priority']!r}")
    for key in ("flags", "policy_ids"):
        val = action[key]
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            return Parsed(False, error=f"{key}_not_string_list")
    unknown = [f for f in action["flags"] if f not in pack.flags]
    if unknown:
        return Parsed(False, error=f"bad_flags:{unknown}")
    # A policy ID that does not exist is not a format failure: the policy_citation component
    # scores it as 0, so it stays visible separately.
    return Parsed(
        True,
        Output(
            reply=reply,
            action=Action(
                type=action["type"],
                queue=action["queue"],
                escalate_to=action["escalate_to"],
                priority=action["priority"],
                flags=tuple(action["flags"]),
                policy_ids=tuple(action["policy_ids"]),
            ),
        ),
    )


def parse(text: str | None, pack: Pack) -> Parsed:
    """Parse one decision-point response. The whole response, stripped, must be the object."""
    if text is None or not text.strip():
        return Parsed(False, error="empty_response")
    body = text.strip()
    try:
        obj = _decode(body)
    except _Dup as dup:
        return Parsed(False, error=f"duplicate_key:{dup}", diagnostics=_diagnostics(body))
    except ValueError:
        return Parsed(False, error="not_json", diagnostics=_diagnostics(body))
    res = check_object(obj, pack)
    if not res.ok:
        return Parsed(False, error=res.error, diagnostics=_diagnostics(body))
    return res
