"""Load a support-rl project: the policy pack, the vocabularies and the scoring config.

A project is a directory with a ``supportrl.yaml`` at its root (see
``recipe/templates/supportrl.yaml`` for the annotated reference). Everything the evaluator
needs to know about *your* support desk comes from that file and the files it points at:

* the policy pack (markdown), and the pattern that finds policy IDs in it
* the model-facing instructions and how session context is rendered
* the controlled vocabularies (queues, priorities, flags, must-ask keys, ...)
* the scoring config: component weights and hard criteria
* the splits, and which of them are locked
"""

from __future__ import annotations

import functools
import hashlib
import re
import string
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

CONFIG_NAME = "supportrl.yaml"

# supportrl's label fields (one decision's answer key)
LABEL_FIELDS = (
    "action_type", "queue", "escalate_to", "priority", "required_flags", "forbidden_flags",
    "must_cite", "may_cite", "must_ask", "prohibited", "allowed_timeline_claims", "rationale",
)  # fmt: skip
COMPONENTS = ("action_type", "destination", "priority", "flags", "policy_citation", "must_ask")
ROUTE, ESCALATE, RESOLVE = "route", "escalate", "resolve"
_MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")


class ConfigError(ValueError):
    pass


def normalize_money(text: str) -> str:
    digits = re.sub(r"[^\d.]", "", text)
    if "." in digits:
        whole, frac = digits.split(".", 1)
        if set(frac) <= {"0"}:
            digits = whole
    return digits.lstrip("0") or "0"


@dataclass(frozen=True)
class HardCriterion:
    code: str
    # exactly one of detector / exact
    detector: str | None = None
    exact: dict | None = None
    # when is this criterion live for a decision?
    when: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    description: str = ""

    @property
    def is_exact(self) -> bool:
        return self.exact is not None

    @property
    def short(self) -> str:
        return self.code.split("_")[0]


@dataclass(frozen=True)
class Split:
    name: str
    file: Path
    locked: bool = False


@dataclass(frozen=True)
class Subset:
    name: str
    split: str
    ids: tuple[str, ...] | None = None
    exclude: str | None = None


class _ContextFormatter(string.Formatter):
    """``{field}`` plus two conveniences: ``{flag:yesno}`` and ``{iso_time:%A %H:%M}``."""

    def format_field(self, value: Any, spec: str) -> str:
        if spec == "yesno":
            return "yes" if value else "no"
        if spec.startswith("%"):
            return datetime.fromisoformat(str(value)).strftime(spec)
        return super().format_field(value, spec)


class Pack:
    """A loaded project. Cheap to construct; everything derived is cached."""

    def __init__(self, root: str | Path, variant: str | None = None):
        root = Path(root).resolve()
        cfg_path = root / CONFIG_NAME if root.is_dir() else root
        if not cfg_path.exists():
            raise ConfigError(f"no {CONFIG_NAME} in {root}")
        self.root = cfg_path.parent
        self.config_path = cfg_path
        self.raw: dict = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        c = self.raw
        self.variant = variant
        self.variants: tuple[str, ...] = tuple(c.get("scoring_variants") or ())
        if variant:
            if variant not in self.variants:
                raise ConfigError(f"unknown scoring variant {variant!r}; have {list(self.variants)}")
            # A variant replaces top-level keys of `scoring` (e.g. adds decision_gates, bumps version).
            c = {**c, "scoring": {**(c.get("scoring") or {}), **c["scoring_variants"][variant]}}
        self.name: str = c.get("name") or self.root.name
        self.title: str = c.get("title", self.name)

        self.policy_pack_path = self.root / c.get("policy_pack", "policies.md")
        self.policy_id_pattern = re.compile(c.get("policy_id_pattern", r"\*\*([A-Z]{2,5}-\d{2,3})\b"))
        self.policy_id_format = re.compile(c.get("policy_id_format", r"^[A-Z]{2,5}-\d{2,3}$"))

        p = c.get("prompt") or {}
        self.instructions_path = self.root / p.get("instructions", "prompt.md")
        self.prompt_version: str = p.get("version", "prompt-v1")
        self.context_template: str = p.get("context_template", "")
        self.customer_header: str = p.get("customer_header", "")

        v = c.get("vocab") or {}
        self.action_types: tuple[str, ...] = tuple(v.get("action_types", ()))
        # "ask" actions (ask for verification / a missing fact): missed/over-ask diagnostics
        self.ask_types: frozenset[str] = frozenset(v.get("ask_types", ()))
        self.queues: frozenset[str] = frozenset(v.get("queues", ()))
        self.priorities: tuple[str, ...] = tuple(v.get("priorities", ()))  # highest first
        self.flags: frozenset[str] = frozenset(v.get("flags", ()))
        self.standing_flags: frozenset[str] = frozenset(v.get("standing_flags", ()))
        self.must_ask: dict[str, str] = dict(v.get("must_ask", {}))
        self.prohibited: frozenset[str] = frozenset(v.get("prohibited", ()))
        self.families: frozenset[str] = frozenset(v.get("families", ()))
        self.difficulties: frozenset[str] = frozenset(v.get("difficulties", ()))

        e = c.get("episodes") or {}
        self.id_pattern = re.compile(e.get("id_pattern", r"^[A-Za-z0-9_.-]+$"))
        self.max_decisions: int = int(e.get("max_decisions", 3))
        self.context_schema: dict = dict(e.get("context", {}))
        self.pii_digit_run: int = int(e.get("pii_digit_run", 7))
        self.coverage_split: str | None = e.get("full_family_coverage")
        # Label field names in your data -> supportrl's names, applied on load. Lets a project keep
        # an existing dataset byte-identical, e.g. {required_policy_ids: must_cite}.
        self.field_aliases: dict[str, str] = dict(e.get("field_aliases", {}))
        bad = set(self.field_aliases.values()) - set(LABEL_FIELDS)
        if bad:
            raise ConfigError(f"episodes.field_aliases maps to unknown label fields {sorted(bad)}")

        s = c.get("scoring") or {}
        self.scorer_version: str = s.get("version", "supportrl")
        self.weights: dict[str, float] = {k: float(s.get("weights", {}).get(k, 0.0)) for k in COMPONENTS}
        self.episode_hard_fail: bool = bool(s.get("episode_hard_fail", True))
        self.probe_recall_floor: float = float(s.get("probe_recall_floor", 0.9))
        self.hard_criteria: tuple[HardCriterion, ...] = tuple(
            HardCriterion(
                code=h["code"],
                detector=h.get("detector"),
                exact=h.get("exact"),
                when=h.get("when") or {},
                options=h.get("options") or {},
                description=h.get("description", ""),
            )
            for h in s.get("hard_criteria", ())
        )
        # Decision gates zero one decision (not the episode) when their condition fails, e.g.
        # {name: ask_gate, when_target_type_in: [ask_verification], require: same_type}
        self.decision_gates: list[dict] = list(s.get("decision_gates", ()))
        self.plugins: tuple[str, ...] = tuple(s.get("plugins", ()))
        self.probes_dir = self.root / s.get("probes", "probes")

        self.label_rules: list[dict] = list(c.get("label_rules", ()))
        self.follow_up_rule: dict = dict(c.get("follow_up_rule", {"enabled": True}))

        self.splits: dict[str, Split] = {}
        for name, spec in (c.get("splits") or {}).items():
            spec = spec if isinstance(spec, dict) else {"file": spec}
            self.splits[name] = Split(name, self.root / spec["file"], bool(spec.get("locked", False)))
        self.subsets: dict[str, Subset] = {}
        for name, spec in (c.get("subsets") or {}).items():
            ids = spec.get("ids")
            self.subsets[name] = Subset(name, spec["split"], tuple(ids) if ids else None, spec.get("exclude"))
        self.selection: dict = dict(c.get("selection", {}))
        self.inference: dict = dict(c.get("inference", {}))
        # optional: the license of the project's data, copied into exports (site-data)
        self.data_license: dict = dict(c.get("data_license", {}))
        self.train: dict = dict(c.get("train", {}))
        self._check()

    # ------------------------------------------------------------------ config sanity
    def _check(self) -> None:
        problems = []
        if not self.policy_pack_path.exists():
            problems.append(f"policy pack not found: {self.policy_pack_path}")
        if not self.instructions_path.exists():
            problems.append(f"prompt instructions not found: {self.instructions_path}")
        for need in (ROUTE, ESCALATE):
            if need not in self.action_types:
                problems.append(f"vocab.action_types must include {need!r}")
        if not self.queues or not self.priorities:
            problems.append("vocab.queues and vocab.priorities must be non-empty")
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            problems.append(f"scoring.weights must sum to 1.0 (got {total:.4f})")
        codes = [h.code for h in self.hard_criteria]
        if len(codes) != len(set(codes)):
            problems.append("hard criterion codes must be unique")
        for h in self.hard_criteria:
            if (h.detector is None) == (h.exact is None):
                problems.append(f"{h.code}: give exactly one of `detector` or `exact`")
        bad_std = self.standing_flags - self.flags
        if bad_std:
            problems.append(f"vocab.standing_flags not in vocab.flags: {sorted(bad_std)}")
        for g in self.decision_gates:
            if g.get("require") != "same_type" or not g.get("name"):
                problems.append(f"decision gate {g}: needs a name and `require: same_type`")
        for sub in self.subsets.values():
            if sub.split not in self.splits:
                problems.append(f"subset {sub.name}: unknown split {sub.split!r}")
        if problems:
            raise ConfigError(f"{self.config_path}:\n  " + "\n  ".join(problems))

    # ------------------------------------------------------------------ pack text
    @functools.cached_property
    def policy_text(self) -> str:
        return self.policy_pack_path.read_text(encoding="utf-8")

    @functools.cached_property
    def policy_ids(self) -> frozenset[str]:
        return frozenset(self.policy_id_pattern.findall(self.policy_text))

    @functools.cached_property
    def policy_money_amounts(self) -> frozenset[str]:
        """Currency figures the pack itself states: quoting one is not disclosing an account fact."""
        return frozenset(normalize_money(m) for m in _MONEY_RE.findall(self.policy_text))

    @functools.cached_property
    def must_ask_patterns(self) -> dict[str, re.Pattern]:
        return {k: re.compile(v, re.IGNORECASE) for k, v in self.must_ask.items()}

    @functools.cached_property
    def instructions(self) -> str:
        return self.instructions_path.read_text(encoding="utf-8")

    def system_prompt(self) -> str:
        return self.instructions + self.policy_text

    def render_context(self, ctx: dict) -> str:
        return _ContextFormatter().format(self.context_template, **ctx)

    # ------------------------------------------------------------------ helpers
    @functools.cached_property
    def priority_rank(self) -> dict[str, int]:
        n = len(self.priorities)
        return {p: n - i for i, p in enumerate(self.priorities)}

    def hard(self, code: str) -> HardCriterion:
        for h in self.hard_criteria:
            if h.code == code:
                return h
        raise KeyError(code)

    def resolve_code(self, name: str) -> str:
        """Accept a full code (``H4_advice_given``) or its short form (``H4``)."""
        for h in self.hard_criteria:
            if name in (h.code, h.short):
                return h.code
        raise KeyError(f"unknown hard criterion {name!r}; have {[h.code for h in self.hard_criteria]}")

    def sha256(self) -> dict[str, str]:
        def h(b: bytes) -> str:
            return hashlib.sha256(b).hexdigest()

        out = {
            "config": h(self.config_path.read_bytes()),
            "policy_pack": h(self.policy_text.encode()),
            "system_prompt": h(self.system_prompt().encode()),
        }
        for s in self.splits.values():
            if s.file.exists():
                out[f"split:{s.name}"] = h(s.file.read_bytes())
        return out


@functools.lru_cache(maxsize=16)
def load_pack(root: str, variant: str | None = None) -> Pack:
    return Pack(root, variant)
