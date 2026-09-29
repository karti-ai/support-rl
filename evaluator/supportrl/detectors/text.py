"""Sentence and clause segmentation, and negation, shared by the detectors.

Detectors judge each regex match on its own, inside its own clause. A negated first match
never hides a later un-negated one: "I can't tell you the balance ... your balance is
$4,100" still fires.
"""

from __future__ import annotations

import re

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])[\"'”’)]*\s+|\n+")
# Clause boundaries: ; : a spaced dash, and contrastive / coordinating conjunctions. A colon
# between digits is a clock time ("10:30"), not a boundary.
_CLAUSE_BREAK = re.compile(
    r"\s*(?:;|(?<!\d):|:(?!\d)|\s[—–-]\s|,\s*(?:but|however|although|though|and|so|yet|while|whereas)\b|"
    r"\b(?:but|however|although|whereas)\b)\s*",
    re.IGNORECASE,
)
NEGATION = re.compile(
    r"\b(?:not|no|never|cannot|can't|can’t|unable|won't|won’t|isn't|isn’t|doesn't|"
    r"doesn’t|don't|don’t|didn't|didn’t|wasn't|wasn’t|aren't|aren’t|shouldn't|"
    r"couldn't|wouldn't|nothing|neither|nor|without)\b|n't\b|n’t\b",
    re.IGNORECASE,
)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(text) if s and s.strip()]


def clauses(sentence: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_BREAK.split(sentence) if c and c.strip()]


def negated_before(clause: str, pos: int) -> bool:
    return bool(NEGATION.search(clause[:pos]))


def is_question(clause: str) -> bool:
    return clause.rstrip().endswith("?")


def compile_named(patterns: dict[str, str] | list, flags=re.IGNORECASE) -> list[tuple[str, re.Pattern]]:
    items = patterns.items() if isinstance(patterns, dict) else patterns
    return [(name, re.compile(p, flags)) for name, p in items]
