"""Text detectors for hard criteria that cannot be checked exactly.

A detector is a class registered under a name. The project config refers to it by that
name and passes ``options``::

    hard_criteria:
      - code: H4_advice_given
        detector: investment_advice
        options: {firm_names: [acme]}

Built in:

  ``disclosure``          account-specific facts stated before the caller is verified
  ``investment_advice``   buy/sell/hold recommendations, rankings of options, market calls
  ``timeline``            a *commitment* to a timeline the decision does not allow

Your own: put a Python file in the project, list it under ``scoring.plugins``, and decorate a
class with ``@register_detector("name")``. See ``evaluator/README.md``.

Detectors are regression detectors with measured error bars, not guarantees. Every run
should report their recall and precision on hand-labelled probe sets (``supportrl probes``).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..pack import Pack


@dataclass(frozen=True)
class Hit:
    rule: str
    excerpt: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.excerpt}"


@dataclass(frozen=True)
class DetectorInput:
    reply: str
    customer_texts: list[str] = field(default_factory=list)  # customer turns seen so far
    context: dict = field(default_factory=dict)  # the episode's session context
    target: dict = field(default_factory=dict)  # the decision's labels (may be empty)


class Detector:
    """Subclass and implement ``detect``. ``options`` come from the project config."""

    def __init__(self, pack: Pack, options: dict):
        self.pack = pack
        self.options = options

    def detect(self, inp: DetectorInput) -> list[Hit]:  # pragma: no cover - interface
        raise NotImplementedError


_REGISTRY: dict[str, type[Detector]] = {}


def register_detector(name: str) -> Callable[[type[Detector]], type[Detector]]:
    def deco(cls: type[Detector]) -> type[Detector]:
        _REGISTRY[name] = cls
        return cls

    return deco


def registered() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)


def _load_builtins() -> None:
    from . import advice, disclosure, timeline  # noqa: F401  (registration side effect)


_loaded_plugins: set[Path] = set()


def load_plugins(pack: Pack) -> None:
    for rel in pack.plugins:
        path = (pack.root / rel).resolve()
        if path in _loaded_plugins:
            continue
        spec = importlib.util.spec_from_file_location(f"supportrl_plugin_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load plugin {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _loaded_plugins.add(path)


def build(name: str, pack: Pack, options: dict) -> Detector:
    _load_builtins()
    load_plugins(pack)
    if name not in _REGISTRY:
        raise KeyError(f"unknown detector {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name](pack, options)
