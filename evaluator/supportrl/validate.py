"""``supportrl validate``: check a project before anything is trained or scored on it.

Structure, controlled vocabularies, policy-ID existence (with did-you-mean), internal label
consistency, the project's own label rules, the follow-up ranking rule, cross-split
leakage (ids and duplicated opening turns), coverage, and the probe files. Errors exit
non-zero. Warnings are things a human should look at: a long digit run in customer text
(an intended PII trap, or a real number that should not be there?), unreviewed episodes.

The validator is the first thing to write for a new pack and it should be strict: it is what
lets several authors work in parallel without drifting apart. But it only checks what
someone already knew to specify. See recipe/AUTHORING.md for what it cannot catch.
"""

from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from .data import decisions_dict, is_reviewed
from .pack import ESCALATE, ROUTE, ConfigError, Pack


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")

    @property
    def ok(self) -> bool:
        return not self.errors

    def format(self, max_warnings: int = 50) -> str:
        lines = list(self.info)
        for w in self.warnings[:max_warnings]:
            lines.append(f"  WARN  {w}")
        if len(self.warnings) > max_warnings:
            lines.append(f"  ... {len(self.warnings) - max_warnings} more warnings")
        lines.extend(f"  FAIL  {e}" for e in self.errors)
        lines.append(f"\n{len(self.errors)} error(s), {len(self.warnings)} warning(s)")
        return "\n".join(lines)


def _check_context(pack: Pack, ctx, where: str, r: Report) -> None:
    if not isinstance(ctx, dict):
        r.err(where, "context missing or not an object")
        return
    for key, spec in pack.context_schema.items():
        val = ctx.get(key)
        if spec == "bool" and not isinstance(val, bool):
            r.err(where, f"context.{key} must be a boolean")
        elif spec == "int" and (not isinstance(val, int) or isinstance(val, bool)):
            r.err(where, f"context.{key} must be an integer")
        elif spec == "str" and not isinstance(val, str):
            r.err(where, f"context.{key} must be a string")
        elif spec == "datetime":
            try:
                datetime.fromisoformat(str(val))
            except ValueError:
                r.err(where, f"context.{key} {val!r} is not an ISO datetime")
        elif isinstance(spec, dict):
            if "enum" in spec and val not in spec["enum"]:
                r.err(where, f"context.{key} {val!r} not in {spec['enum']}")
            if "pattern" in spec and not re.match(spec["pattern"], str(val)):
                r.err(where, f"context.{key} {val!r} does not match {spec['pattern']}")


def _check_turns(pack: Pack, rec: dict, where: str, r: Report) -> list[str]:
    turns = rec.get("turns")
    if not isinstance(turns, list) or not turns:
        r.err(where, "turns missing or empty")
        return []
    points = []
    digit_run = re.compile(rf"(?<!\d)\d{{{pack.pii_digit_run},}}(?!\d)")
    for i, t in enumerate(turns):
        tw = f"{where}.turns[{i}]"
        if t.get("t") != i:
            r.err(tw, f"t={t.get('t')} does not match position {i}")
        role = t.get("role")
        if role == "customer":
            text = t.get("text")
            if not isinstance(text, str) or not text.strip():
                r.err(tw, "customer turn has no text")
            elif pack.pii_digit_run:
                for hit in digit_run.findall(text):
                    r.warn(tw, f"customer text has a {len(hit)}-digit run ({hit}): an intended PII trap? "
                               "Make sure it is not a real, valid number")  # fmt: skip
            if t.get("decision_point"):
                r.err(tw, "customer turn must not carry a decision_point")
        elif role == "agent":
            if t.get("text"):
                r.err(tw, "agent turn must not carry text: the model produces it")
            dp = t.get("decision_point")
            if not isinstance(dp, str) or not re.match(r"^d\d+$", dp):
                r.err(tw, f"decision_point {dp!r} must be d1, d2, ...")
            else:
                points.append(dp)
        else:
            r.err(tw, f"role {role!r} is not customer|agent")
    if turns[0].get("role") != "customer":
        r.err(where, "an episode must open with a customer turn")
    if turns[-1].get("role") != "agent":
        r.err(where, "an episode must end at an agent decision point")
    for a, b in zip(turns, turns[1:]):
        if a.get("role") == b.get("role"):
            r.err(where, f"consecutive {a.get('role')} turns at t={a.get('t')}")
    if points != [f"d{i}" for i in range(1, len(points) + 1)]:
        r.err(where, f"decision points {points} are not d1..dN in order")
    if not 1 <= len(points) <= pack.max_decisions:
        r.err(where, f"{len(points)} decision points; expected 1..{pack.max_decisions}")
    return points


def _dest(d: dict):
    return d.get("escalate_to") if d.get("action_type") == ESCALATE else d.get("queue")


def _rule_applies(rule: dict, d: dict, seen_flag: set[str]) -> bool:
    req = set(d.get("required_flags") or [])
    if "when_required_flag" in rule and rule["when_required_flag"] not in req:
        return False
    if "when_true" in rule and not d.get(rule["when_true"]):
        return False
    if "from_required_flag" in rule and rule["from_required_flag"] not in seen_flag:
        return False
    return True


def _rule_violations(req: dict, d: dict) -> list[str]:
    out = []
    if "action_type" in req and d.get("action_type") != req["action_type"]:
        out.append(f"action_type must be {req['action_type']}")
    if "destination" in req and req["destination"] not in (d.get("queue"), d.get("escalate_to")):
        out.append(f"must reach {req['destination']}")
    if "priority" in req and d.get("priority") != req["priority"]:
        out.append(f"priority must be {req['priority']}")
    if "allowed_timeline_claims_include" in req and req["allowed_timeline_claims_include"] not in (
        d.get("allowed_timeline_claims") or []
    ):
        out.append(f"allowed_timeline_claims must include {req['allowed_timeline_claims_include']!r}")
    if "may_cite_include" in req and req["may_cite_include"] not in (d.get("may_cite") or []):
        out.append(f"may_cite must include {req['may_cite_include']}")
    if "must_ask_exclude" in req and req["must_ask_exclude"] in (d.get("must_ask") or []):
        out.append(f"must_ask must not include {req['must_ask_exclude']}")
    return out


def _check_decisions(pack: Pack, rec: dict, points: list[str], where: str, r: Report) -> None:
    if pack.families and rec.get("family") not in pack.families:
        r.err(where, f"family {rec.get('family')!r} not in vocab.families")
    if pack.difficulties and rec.get("difficulty") not in pack.difficulties:
        r.err(where, f"difficulty {rec.get('difficulty')!r} not in vocab.difficulties")
    try:
        decisions = decisions_dict(rec, pack.field_aliases)
    except (KeyError, TypeError, AttributeError):
        r.err(where, "decisions malformed")
        return
    if list(decisions) != points:
        r.err(where, f"labelled decisions {list(decisions)} do not match the turns' {points}")
    gate_fields = {h.when.get("target_false") for h in pack.hard_criteria} | {
        h.when.get("target_true") for h in pack.hard_criteria
    }
    gate_fields.discard(None)
    timeline_fields = {
        h.options.get("allowed_field", "allowed_timeline_claims")
        for h in pack.hard_criteria
        if h.detector == "timeline"
    }
    seen_flags: set[str] = set()
    standing = None
    for dp, d in decisions.items():
        dw = f"{where}.{dp}"
        at = d.get("action_type")
        if at not in pack.action_types:
            r.err(dw, f"action_type {at!r} not in vocab.action_types")
        q, e, p = d.get("queue"), d.get("escalate_to"), d.get("priority")
        if at == ROUTE:
            if q not in pack.queues:
                r.err(dw, f"route needs a valid queue, got {q!r}")
            if e is not None:
                r.err(dw, "route must have escalate_to null")
            if p not in pack.priorities:
                r.err(dw, f"route needs a priority, got {p!r}")
        elif at == ESCALATE:
            if e not in pack.queues:
                r.err(dw, f"escalate needs a valid escalate_to, got {e!r}")
            if q is not None:
                r.err(dw, "escalate must have queue null")
            if p not in pack.priorities:
                r.err(dw, f"escalate needs a priority, got {p!r}")
        elif q is not None or e is not None or p is not None:
            r.err(dw, f"{at} must have queue, escalate_to and priority all null")
        req_f, forb_f = set(d.get("required_flags") or []), set(d.get("forbidden_flags") or [])
        for f in (req_f | forb_f) - pack.flags:
            r.err(dw, f"flag {f!r} not in vocab.flags")
        if req_f & forb_f:
            r.err(dw, f"flags both required and forbidden: {sorted(req_f & forb_f)}")
        req_p, acc_p = d.get("must_cite"), d.get("may_cite")
        if not isinstance(req_p, list) or not isinstance(acc_p, list):
            r.err(dw, "must_cite and may_cite must both be lists")
            req_p, acc_p = req_p or [], acc_p or []
        if not acc_p:
            r.err(dw, "may_cite is empty")
        for pid in set(req_p) | set(acc_p):
            if not pack.policy_id_format.match(str(pid)):
                r.err(dw, f"policy id {pid!r} is malformed")
            elif pid not in pack.policy_ids:
                near = difflib.get_close_matches(str(pid), sorted(pack.policy_ids), 1)
                r.err(
                    dw,
                    f"policy id {pid} is not in the policy pack"
                    + (f" (did you mean {near[0]}?)" if near else ""),
                )
        if not set(req_p) <= set(acc_p):
            r.err(dw, f"must_cite not a subset of acceptable: {sorted(set(req_p) - set(acc_p))}")
        for k in d.get("must_ask") or []:
            if k not in pack.must_ask:
                r.err(dw, f"must_ask key {k!r} not in vocab.must_ask")
        for k in d.get("prohibited") or []:
            if pack.prohibited and k not in pack.prohibited:
                r.err(dw, f"prohibited class {k!r} not in vocab.prohibited")
        for fld in gate_fields:
            if not isinstance(d.get(fld), bool):
                r.err(dw, f"{fld} must be a boolean (a hard criterion keys on it)")
        for fld in timeline_fields:
            if not isinstance(d.get(fld), list):
                r.err(dw, f"{fld} must be a list (empty is fine)")
        rationale = d.get("rationale")
        if not isinstance(rationale, str) or len(rationale.strip()) < 20:
            r.err(dw, "rationale missing or too short to be useful")
        seen_flags |= req_f
        for rule in pack.label_rules:
            if _rule_applies(rule, d, seen_flags):
                for v in _rule_violations(rule.get("require", {}), d):
                    r.err(dw, f"{rule.get('name', 'label rule')}: {v}")
        # follow-up rule: a later route/escalate must strictly outrank the standing disposition
        if at in (ROUTE, ESCALATE) and pack.follow_up_rule.get("enabled", True):
            if standing is not None:
                new = (at == ESCALATE, pack.priority_rank.get(p, -1))
                old = (
                    standing.get("action_type") == ESCALATE,
                    pack.priority_rank.get(standing.get("priority"), -1),
                )
                exc = pack.follow_up_rule.get("same_rank_exception_destination")
                same_rank_ok = (
                    exc is not None
                    and new == old
                    and at == ESCALATE
                    and _dest(d) == exc
                    and _dest(standing) != exc
                )
                if not (new > old or same_rank_ok):
                    r.err(dw, f"follow-up {at} {_dest(d)} {p} does not outrank the standing "
                              f"{standing.get('action_type')} {_dest(standing)} {standing.get('priority')}: "
                              "a follow-up about a matter already routed is `resolve`")  # fmt: skip
            standing = d


def validate(root: str, split: str | None = None) -> Report:
    r = Report()
    try:
        pack = Pack(root)
    except ConfigError as exc:
        r.errors.append(str(exc))
        return r
    if not pack.policy_ids:
        r.err("policy_pack", f"no policy ids found with pattern {pack.policy_id_pattern.pattern!r}")
    r.info.append(f"project {pack.name}: policy pack {len(pack.policy_ids)} policy ids, "
                  f"scoring {pack.scorer_version}, {len(pack.hard_criteria)} hard criteria")  # fmt: skip
    for code in (h.code for h in pack.hard_criteria if h.detector):
        try:
            from .scorer import Scorer

            Scorer(pack).detector(code)
        except Exception as exc:  # noqa: BLE001
            r.err(code, f"detector failed to build: {exc}")
            break
    names = [split] if split else list(pack.splits)
    seen_ids: dict[str, str] = {}
    openings: dict[str, str] = {}
    ids_by_split: dict[str, set[str]] = {}
    for name in names:
        if name not in pack.splits:
            r.err("splits", f"unknown split {name!r}")
            continue
        sp = pack.splits[name]
        if not sp.file.exists():
            r.err(name, f"file missing: {sp.file}")
            continue
        fams, diffs, dcount, unreviewed = Counter(), Counter(), 0, 0
        rows = []
        for n, line in enumerate(sp.file.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    r.err(f"{sp.file.name}:{n}", f"invalid JSON: {exc}")
        ids_by_split[name] = set()
        for rec in rows:
            rid = str(rec.get("id", "<no id>"))
            where = f"{name}[{rid}]"
            if not pack.id_pattern.match(rid):
                r.err(where, f"id does not match {pack.id_pattern.pattern}")
            if rid in seen_ids:
                r.err(where, f"id already used in {seen_ids[rid]}")
            seen_ids[rid] = name
            ids_by_split[name].add(rid)
            _check_context(pack, rec.get("context"), where, r)
            points = _check_turns(pack, rec, where, r)
            if not is_reviewed(rec):
                unreviewed += 1
                if rec.get("decisions"):
                    r.warn(where, "unreviewed episode carries labels: review it and mark status reviewed")
            else:
                _check_decisions(pack, rec, points, where, r)
                fams[rec.get("family")] += 1
                diffs[rec.get("difficulty")] += 1
                dcount += len(points)
            first = " ".join(str((rec.get("turns") or [{}])[0].get("text", "")).lower().split())[:120]
            if first in openings:
                r.err(where, f"opening turn duplicates {openings[first]} (leakage across or within splits)")
            elif first:
                openings[first] = rid
        if unreviewed:
            r.warn(name, f"{unreviewed} unreviewed episode(s) are skipped by every loader until labelled")
        r.info.append(f"{name}: {len(rows) - unreviewed} episodes, {dcount} decisions; "
                      f"difficulty {dict(sorted(diffs.items(), key=lambda x: str(x[0])))}")  # fmt: skip
        if name == pack.coverage_split and pack.families:
            missing = pack.families - set(fams)
            if missing:
                r.warn("coverage", f"{name} does not cover families: {sorted(missing)}")
    for sub in pack.subsets.values():
        if sub.ids and sub.split in ids_by_split:
            missing = set(sub.ids) - ids_by_split[sub.split]
            if missing:
                r.err(f"subset {sub.name}", f"ids not in split {sub.split}: {sorted(missing)}")
    if pack.probes_dir.exists():
        from .data import read_jsonl

        for f in sorted(pack.probes_dir.glob("*.jsonl")):
            for p in read_jsonl(f):
                try:
                    pack.resolve_code(p["detector"])
                    assert p["label"] in ("violation", "clean") and isinstance(p["reply"], str)
                except (KeyError, AssertionError):
                    r.err(
                        f"probes/{f.name}",
                        f"bad probe {p.get('id')}: needs detector, label violation|clean, reply",
                    )
    return r


def validate_candidates(root: str, path: str) -> Report:
    """Structure-only checks for generated candidates (they have no labels yet)."""
    r = Report()
    pack = Pack(root)
    from .data import read_jsonl

    rows = read_jsonl(path)
    for rec in rows:
        where = f"candidate[{rec.get('id')}]"
        _check_context(pack, rec.get("context"), where, r)
        _check_turns(pack, rec, where, r)
        if is_reviewed(rec) and not rec.get("decisions"):
            r.err(where, "marked reviewed but has no decisions (labels)")
    n_unrev = sum(not is_reviewed(x) for x in rows)
    r.info.append(
        f"{path}: {len(rows)} candidates, {n_unrev} unreviewed (skipped by every loader until labelled)"
    )
    return r
