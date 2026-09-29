"""The reward: deterministic code, no model calls.

    stage 1  FORMAT GATE      the output contract holds          else decision = 0
    stage 2  HARD CRITERIA    configured non-negotiables         any (non-advisory) hit: episode = 0
    stage 3  GRADED           weighted sum over six components   0 .. 1

Episode reward is the mean over its decision points, except that a non-advisory hard
violation at any decision point zeroes the whole episode (``scoring.episode_hard_fail``). A
model that verifies correctly at d1 and leaks the balance at d2 has failed the conversation.

Graded components (weights from ``scoring.weights``):

  action_type      exact match
  destination      queue for a route, escalate_to for an escalation; exact. 0 whenever the
                   type is wrong. For non-routing targets, both destination fields must be null
  priority         exact, no credit for adjacent bands
  flags            F1 against required_flags; any forbidden flag scores 0. Standing flags from
                   an earlier route/escalate are neutral on later decisions
  policy_citation  recall over must_cite x precision against may_cite;
                   citing an ID that is not in the pack scores 0
  must_ask         fraction of must_ask keys the reply actually asks for
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import fsum

from . import detectors as det
from .contract import Action, Output, parse
from .data import customer_texts_by_decision
from .detectors.must_ask import asked
from .pack import COMPONENTS, ESCALATE, RESOLVE, ROUTE, Pack

SCORER_VERSION = "supportrl-scorer-1"


@dataclass
class DecisionScore:
    decision_id: str
    format_valid: bool
    format_error: str | None
    format_diagnostics: dict
    hard: dict[str, list[str]]  # code -> evidence (empty = clean)
    hard_zeroing: list[str]  # codes that actually zeroed it (non-advisory)
    components: dict[str, float]
    graded: float  # weighted sum before the hard gate
    score: float  # after the gates
    target_action_type: str
    model_action_type: str | None
    over_escalation: bool
    under_escalation: bool
    under_route: bool
    missed_ask: bool = False  # target is an ask type, the model emitted another type
    over_ask: bool = False  # the model asked where the target does not
    gates: list[str] = field(default_factory=list)  # decision gates that zeroed this decision
    reply: str | None = None
    action: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EpisodeScore:
    episode_id: str
    reward: float
    decisions: list[DecisionScore] = field(default_factory=list)
    hard_failed: bool = False
    missing_decisions: int = 0
    scorer_version: str = SCORER_VERSION
    config_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _live(when: dict, target: dict) -> bool:
    if "target_false" in when and target.get(when["target_false"]):
        return False
    if "target_true" in when and not target.get(when["target_true"]):
        return False
    if "required_flag" in when and when["required_flag"] not in (target.get("required_flags") or []):
        return False
    return True


def _exact_ok(require: dict, a: Action) -> bool:
    if "type" in require and a.type != require["type"]:
        return False
    if "destination" in require and a.destination != require["destination"]:
        return False
    if "priority" in require and a.priority != require["priority"]:
        return False
    need = require.get("flags_include", [])
    need = [need] if isinstance(need, str) else need
    return all(f in a.flags for f in need)


class Scorer:
    def __init__(self, pack: Pack):
        self.pack = pack
        self.weights = pack.weights
        self.codes = tuple(h.code for h in pack.hard_criteria)
        self.exact_codes = frozenset(h.code for h in pack.hard_criteria if h.is_exact)
        self._detectors = {
            h.code: det.build(h.detector, pack, h.options) for h in pack.hard_criteria if h.detector
        }

    def detector(self, code: str) -> det.Detector:
        return self._detectors[code]

    def check_advisory(self, advisory) -> frozenset[str]:
        adv = frozenset(self.pack.resolve_code(a) for a in (advisory or ()))
        exact = adv & self.exact_codes
        if exact:
            raise ValueError(f"{sorted(exact)} are exact checks and cannot be made advisory")
        return adv

    # ---------------------------------------------------------------- components
    def _destination(self, t: dict, a: Action) -> float:
        tt = t["action_type"]
        if a.type != tt:
            return 0.0
        if tt == ROUTE:
            return float(a.queue == t["queue"] and a.escalate_to is None)
        if tt == ESCALATE:
            return float(a.escalate_to == t["escalate_to"])
        return float(a.queue is None and a.escalate_to is None)

    @staticmethod
    def _flags(t: dict, a: Action, neutral: frozenset[str]) -> float:
        got = set(a.flags)
        if got & set(t.get("forbidden_flags") or []):
            return 0.0
        req = set(t.get("required_flags") or [])
        got -= neutral - req
        if not req and not got:
            return 1.0
        tp = len(req & got)
        if not req or not got or tp == 0:
            return 0.0
        p, r = tp / len(got), tp / len(req)
        return 2 * p * r / (p + r)

    def _citation(self, t: dict, a: Action) -> float:
        cited = set(a.policy_ids)
        if cited - self.pack.policy_ids:
            return 0.0
        req = set(t.get("must_cite") or [])
        acc = set(t.get("may_cite") or []) | req
        recall = len(req & cited) / len(req) if req else 1.0
        precision = len(cited & acc) / len(cited) if cited else (1.0 if not req else 0.0)
        return recall * precision

    def _must_ask(self, t: dict, reply: str) -> float:
        keys = t.get("must_ask") or []
        if not keys:
            return 1.0
        return fsum(asked(self.pack, reply, k) for k in keys) / len(keys)

    # ---------------------------------------------------------------- hard criteria
    def hard_criteria(
        self, t: dict, out: Output, customer_texts: list[str], context: dict
    ) -> dict[str, list[str]]:
        res: dict[str, list[str]] = {c: [] for c in self.codes}
        inp = det.DetectorInput(out.reply, customer_texts, context, t)
        a = out.action
        for h in self.pack.hard_criteria:
            if h.is_exact:
                when = dict(h.when)
                if "when_required_flag" in h.exact:
                    when["required_flag"] = h.exact["when_required_flag"]
                if _live(when, t) and not _exact_ok(h.exact.get("require", {}), a):
                    res[h.code] = [
                        f"type={a.type} dest={a.destination} priority={a.priority} flags={list(a.flags)}"
                    ]
            elif _live(h.when, t):
                res[h.code] = [str(x) for x in self._detectors[h.code].detect(inp)]
        return res

    # ---------------------------------------------------------------- decisions / episodes
    def score_decision(
        self,
        decision_id: str,
        target: dict,
        response: str | None,
        customer_texts: list[str],
        context: dict | None = None,
        advisory: frozenset[str] = frozenset(),
        standing_flags: frozenset[str] = frozenset(),
    ) -> DecisionScore:
        parsed = parse(response, self.pack)
        tt = target["action_type"]
        if not parsed.ok:
            return DecisionScore(
                decision_id, False, parsed.error, parsed.diagnostics, {c: [] for c in self.codes}, [],
                {k: 0.0 for k in COMPONENTS}, 0.0, 0.0, tt, None, False, False, False,
            )  # fmt: skip
        out = parsed.output
        a = out.action
        comps = {
            "action_type": float(a.type == tt),
            "destination": self._destination(target, a),
            "priority": float(a.priority == target.get("priority")),
            "flags": self._flags(target, a, standing_flags),
            "policy_citation": self._citation(target, a),
            "must_ask": self._must_ask(target, out.reply),
        }
        graded = fsum(self.weights[k] * v for k, v in comps.items())
        hard = self.hard_criteria(target, out, customer_texts, context or {})
        zeroing = [c for c, ev in hard.items() if ev and c not in advisory]
        gates = [
            g["name"] for g in self.pack.decision_gates
            if tt in g.get("when_target_type_in", ()) and a.type != tt
        ]  # fmt: skip
        routing = (ROUTE, ESCALATE)
        asks = self.pack.ask_types
        return DecisionScore(
            decision_id=decision_id,
            format_valid=True,
            format_error=None,
            format_diagnostics={},
            hard=hard,
            hard_zeroing=zeroing,
            components=comps,
            graded=graded,
            score=0.0 if (zeroing or gates) else graded,
            target_action_type=tt,
            model_action_type=a.type,
            over_escalation=a.type == ESCALATE and tt != ESCALATE,
            under_escalation=tt == ESCALATE and a.type != ESCALATE,
            under_route=a.type == RESOLVE and tt in routing,
            missed_ask=tt in asks and a.type != tt,
            over_ask=a.type in asks and tt not in asks,
            gates=gates,
            reply=out.reply,
            action=a.to_dict(),
        )

    def score_episode(self, episode: dict, responses: list[str | None], advisory=()) -> EpisodeScore:
        """``responses``: the model's assistant messages in order. A missing one scores 0."""
        adv = self.check_advisory(advisory)
        seen = customer_texts_by_decision(episode)
        decisions: list[DecisionScore] = []
        standing: frozenset[str] = frozenset()
        for i, dp in enumerate(episode["decisions"]):
            t = episode["decisions"][dp]
            text = responses[i] if i < len(responses) else None
            decisions.append(self.score_decision(dp, t, text, seen[dp], episode["context"], adv, standing))
            if t["action_type"] in (ROUTE, ESCALATE):
                standing = standing | (frozenset(t.get("required_flags") or []) & self.pack.standing_flags)
        hard_failed = any(d.hard_zeroing for d in decisions)
        mean = fsum(d.score for d in decisions) / len(decisions) if decisions else 0.0
        return EpisodeScore(
            episode_id=episode["id"],
            reward=0.0 if (hard_failed and self.pack.episode_hard_fail) else mean,
            decisions=decisions,
            hard_failed=hard_failed,
            missing_decisions=max(0, len(decisions) - len(responses)),
            config_version=self.pack.scorer_version,
        )
