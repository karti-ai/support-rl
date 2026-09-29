"""Scripted customer: replay the episode's written turns, in order, whatever the model says."""

from __future__ import annotations

from dataclasses import dataclass

from supportrl.data import first_user_message, followups
from supportrl.pack import Pack
from supportrl.rollout import run_episode, run_many  # noqa: F401  (re-exported)


@dataclass
class ScriptedCustomer:
    pack: Pack
    episode: dict

    def opening(self) -> str:
        """Session context + the first customer turn."""
        return first_user_message(self.pack, self.episode)

    def reply(self, k: int) -> str | None:
        """The customer turn after the agent's k-th reply (0-based), or None when done."""
        script = followups(self.episode)
        return script[k] if k < len(script) else None

    @property
    def n_decisions(self) -> int:
        return len(self.episode["decisions"])
