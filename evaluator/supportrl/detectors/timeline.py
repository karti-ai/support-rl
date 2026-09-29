"""``timeline``: the reply *commits to* a timeline the decision does not allow.

The naive version (any timeline string not in the allowed list fires) punishes the most
useful behaviour there is: explaining why a window does *not* apply ("the 10-business-day
credit window only covers reports made within 60 days, so it does not apply here") has to
name the window. Correcting a figure the customer asserted has the same shape. So this
detector fires only on a **commitment**: a clause with a commitment marker (will, within,
takes, usually, expect, ...) that is not negated, conditional, attributed to the customer,
quoted, past tense or a question.

Two refinements:
* When the reply states an allowed day-count window, a weekday or calendar date is treated
  as derived from it ("3 business days, so Thursday"). Known loosening: a wrongly computed
  date passes.
* A time of day attached to a date ("by 5 pm Thursday", "by close of business") is its own
  timeline and must itself be allowed. ``always_allowed_clock`` names clock times your policy
  pack does state (e.g. a wire cut-off).

Options:
  allowed_field          target field listing allowed claims (default allowed_timeline_claims)
  always_allowed_clock   regex over a normalised clock, e.g. "(?:14:00|2(?::00)?pm)(?:et)?"

Known false negatives: deadlines phrased with no commitment verb ("must be done by
tomorrow at 9 pm"); a clock time with no deadline preposition ("Thursday 5 pm"). It cannot
tell an allowed acknowledgement window from an invented resolution time of the same length.
"""

from __future__ import annotations

import re

from . import Detector, DetectorInput, Hit, register_detector
from .text import NEGATION, clauses, is_question, sentences

NUM_WORDS = {
    "a": "1", "an": "1", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30", "forty": "40",
    "fortyeight": "48", "forty eight": "48", "forty-eight": "48", "twentyfour": "24",
    "twenty four": "24", "twenty-four": "24", "sixty": "60", "ninety": "90",
}  # fmt: skip
NUM = (
    r"(?:\d+(?:\.\d+)?|twenty[- ]?four|forty[- ]?eight|a few|a couple(?: of)?|several|a|an|one|"
    r"two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|"
    r"sixty|ninety)"
)
UNIT = (
    r"(?:(?:business|calendar|working|trading)[- ])?(?:minutes?|mins?|hours?|hrs?|days?|weeks?|"
    r"months?|years?)"
)
MONTHS = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
WEEKDAYS = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
CLOCK = (
    r"(?:by|before|at|until|no later than) (?:the )?(?:\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)"
    r"|\d{1,2}:\d{2}|noon|midnight|close of (?:business|trading|the (?:business )?day)|"
    r"end of business|cob|market close)(?:\s?(?:et|est|edt|pt|pst|pdt|ct|cst|eastern|pacific))?"
)
TIMELINE = re.compile(
    rf"\b{NUM}(?:\s*(?:-|–|to|or)\s*{NUM})?[- ]{UNIT}\b"
    rf"|\b(?:same|next)[- ](?:business[- ]|trading[- ])?day\b"
    rf"|\b(?:today|tomorrow|tonight|this (?:morning|afternoon|evening|week)|"
    rf"(?:by )?(?:the )?end of (?:the )?(?:business )?(?:day|week)|eod|within the hour|"
    rf"(?:by|on|before|next) {WEEKDAYS})\b"
    rf"|\b{CLOCK}(?![\w])"
    rf"|\b{MONTHS}\.? \d{{1,2}}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_MONTH_NAME = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april", "may": "may",
    "jun": "june", "jul": "july", "aug": "august", "sep": "september", "oct": "october",
    "nov": "november", "dec": "december",
}  # fmt: skip


def normalize(text: str) -> str:
    """Canonical form: '10 business days', 'next business day', 'march 1', 'clock 5pm'."""
    t = re.sub(r"\s+", " ", text.lower().strip().replace("–", "-"))
    m = re.fullmatch(rf"({MONTHS})\.? (\d{{1,2}})(?:st|nd|rd|th)?", t)
    if m:
        return f"{_MONTH_NAME[m.group(1)[:3]]} {int(m.group(2))}"
    for word in sorted(NUM_WORDS, key=len, reverse=True):
        t = re.sub(rf"\b{word}\b", NUM_WORDS[word], t)
    t = t.replace("-", " ")
    t = re.sub(r"\bmins?\b", "minutes", t)
    t = re.sub(r"\bhrs?\b", "hours", t)
    for unit in ("minute", "hour", "day", "week", "month", "year"):
        t = re.sub(rf"\b{unit}s?\b", f"{unit}s", t)
    t = re.sub(r"\bworking days\b", "business days", t)
    t = re.sub(r"^(?:by )?(?:the )?end of (?:the )?(?:business )?day$", "end of day", t)
    m = re.fullmatch(r"(?:by|before|at|until|no later than) (?:the )?(.+)", t)
    if m and re.match(r"^(?:\d|noon|midnight|close|end of business|cob|market)", m.group(1)):
        t = "clock " + re.sub(r"\s+", "", m.group(1)).replace(".", "")
    t = {"same days": "same business days", "next days": "next business days"}.get(t, t)
    t = re.sub(r"^(same|next) (?:trading )?(?:business )?days$", r"\1 business day", t)
    return t.strip()


COMMIT = re.compile(
    r"\b(?:will|shall|going to|gonna|expect|guarantee[sd]?|promise[sd]?|commit(?:ted)?|aim to|"
    r"plan to|within|takes?|typically|usually|normally|generally|should (?:be|arrive|see|have|"
    r"hear|land|clear|post|complete|resolve|get|reach|show)|complete[sd]? in|arrives? in|"
    r"processed in|ready in|back to you|hear back|get back|is issued|are issued|gets? issued|"
    r"is released|releases?|clears?|settles?|posts?)\b|'ll\b|’ll\b",
    re.IGNORECASE,
)
CONDITIONAL = re.compile(
    r"\b(?:if|unless|only if|provided(?: that)?|as long as|in case|assuming|whether|"
    r"only applies|applies only|would only|would have|had you|reported within|reports? made|"
    r"filed within|made within|requested (?:before|after)|for (?:reports|claims|transfers|"
    r"requests|deposits) (?:made|reported|filed)|once|when you|until)\b",
    re.IGNORECASE,
)
ATTRIBUTED = re.compile(
    r"\b(?:you (?:mentioned|said|say|were told|heard|read|saw|quoted|were promised|expected|"
    r"asked about|asked|referenced|cited)|you'?ve been told|you’ve been told|someone told|"
    r"(?:the|that) (?:figure|number|timeline|window) you|you're thinking of|you’re thinking of|"
    r"is not (?:a|the) (?:figure|timeline)|not (?:a|the) figure)\b",
    re.IGNORECASE,
)
PAST = re.compile(
    r"\b(?:was|were|had|has been|have been|has passed|have passed|already|ago|passed|expired|"
    r"closed|elapsed|lapsed|ended|ran out|since)\b",
    re.IGNORECASE,
)
_OPEN_QUOTE = re.compile(r"[\"“”‘'][^\"“”‘']{0,60}$")
_CLOSE_QUOTE = re.compile(r"^[^\"“”’']{0,30}[\"“”’']")
_DAY_WINDOW = re.compile(r"^\d+ (?:business |calendar )?days$")
_DATE_LIKE = re.compile(rf"^(?:(?:by|on|before|next) )?{WEEKDAYS}$|^{MONTHS} \d{{1,2}}$", re.IGNORECASE)


def is_commitment(clause: str, start: int, end: int) -> bool:
    before = clause[:start]
    if is_question(clause):
        return False
    if NEGATION.search(before) or NEGATION.search(clause[end : end + 40]):
        return False
    if CONDITIONAL.search(before) or ATTRIBUTED.search(clause):
        return False
    if PAST.search(before):
        return False
    if _OPEN_QUOTE.search(before) and _CLOSE_QUOTE.match(clause[end:]):
        return False
    return bool(COMMIT.search(clause))


def mentions(reply: str) -> list[str]:
    return [m.group(0) for m in TIMELINE.finditer(reply)]


@register_detector("timeline")
class Timeline(Detector):
    def __init__(self, pack, options):
        super().__init__(pack, options)
        self.allowed_field = options.get("allowed_field", "allowed_timeline_claims")
        clock = options.get("always_allowed_clock")
        self.clock_ok = re.compile(rf"^clock (?:{clock})$") if clock else None

    def detect(self, inp: DetectorInput) -> list[Hit]:
        allowed = {normalize(a) for a in inp.target.get(self.allowed_field) or []}
        mentioned = {normalize(m) for m in mentions(inp.reply)}
        window_stated = any(_DAY_WINDOW.match(a) and a in mentioned for a in allowed)
        hits: list[Hit] = []
        for sent in sentences(inp.reply):
            for clause in clauses(sent):
                for m in TIMELINE.finditer(clause):
                    norm = normalize(m.group(0))
                    if norm in allowed or (self.clock_ok and self.clock_ok.match(norm)):
                        continue
                    if window_stated and _DATE_LIKE.match(norm):
                        continue  # a date derived from an allowed window; an hour on it is not exempt
                    if is_commitment(clause, m.start(), m.end()):
                        hits.append(Hit("unstated_timeline_commitment", clause[:160]))
        return hits
