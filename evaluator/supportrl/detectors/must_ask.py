"""``must_ask``: did the reply actually *ask* for a fact the decision requires?

Each must-ask key has a topic regex in the project config (``vocab.must_ask``). A key is
satisfied when one sentence both matches the topic and makes a request (a question mark,
"please", "could you", "I'll need", "send", "confirm", ...).
"""

from __future__ import annotations

import re

from ..pack import Pack
from .text import sentences

REQUEST = re.compile(
    r"\?|\b(?:please|could you|can you|would you|will you|I(?:'ll|’ll| will)? need|we(?:'ll|’ll| will)? need|"
    r"need (?:you|two|the|your)|provide|send (?:me|us|over|through)?|share|reply with|let me know|tell me|"
    r"confirm|give me|what (?:is|was|are)|which|upload|submit|supply|read (?:me|out))\b",
    re.IGNORECASE,
)


def asked(pack: Pack, reply: str, key: str) -> bool:
    patterns = pack.must_ask_patterns  # compiled once per Pack instance, never shared across packs
    if key not in patterns:
        raise KeyError(f"must_ask key {key!r} has no pattern in vocab.must_ask")
    rx = patterns[key]
    return any(rx.search(s) and REQUEST.search(s) for s in sentences(reply))
