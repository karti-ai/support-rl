"""``disclosure``: an account-specific fact stated to a caller who is not verified.

Live only on decisions whose verification gate is live (the criterion's ``when`` clause
decides that). Fires on:

* a currency amount the customer did not say and the policy pack does not state
* assertions of account state: balances and holdings, "your account shows ...", the status
  of an order, transfer or payment, "I can see the transfer ...", "I can confirm your ..."
* the last four digits of the account on file, when the customer has not said them

It does not fire on questions ("what month was your account opened?" is the verification
ask), embedded questions ("I can confirm whether your account ..."), or negated clauses.

Options:
  masked_field         context field holding the masked account (default ``account_masked``)
  extra_assertions     {name: regex} extra account-state assertions for your domain
  extra_polarity_free  {name: regex} assertions that disclose in either polarity
                       ("you have not used your reset" states a fact as much as "you have")

Known false-negative shapes: third-party possessives ("His positions are still there"),
facts stated without any of the assertion verbs.
"""

from __future__ import annotations

import re

from ..pack import normalize_money
from . import Detector, DetectorInput, Hit, register_detector
from .text import clauses, compile_named, is_question, negated_before, sentences

MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|K|thousand))?")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?(?:\s?(?:k|K|thousand))?")

RECORD_NOUNS = (
    r"account|transfer|transaction|order|trade|deposit|withdrawal|balance|position|"
    r"wire|margin call|call|payment|debit|ach|login|activity|charge|reset|statement"
)

ASSERTIONS = {
    "balance_or_holdings": (
        r"\byour (?:current |available |total |cash |account |settled |remaining |margin )*"
        r"(?:balance|buying power|equity|holdings?|positions?|portfolio|cash)\s+"
        r"(?:is|was|are|were|stands at|shows|sits at|comes to|totals?|of \$)"
    ),
    "you_hold": (
        r"\byou (?:currently |still )?(?:have|hold|own|are holding) (?:about |around |roughly )?"
        r"(?:\$|\d[\d,]* (?:shares|contracts|units)|\d[\d,]*\s+(?:[A-Z]{1,5}\b))"
    ),
    "money_still_there": (
        r"\b(?:the |your )?(?:money|funds|cash) (?:is|are) (?:still )?"
        r"(?:there|safe|in (?:the|your) account|intact|available)"
    ),
    "account_state": (
        r"\b(?:your|his|her|their|the) account (?:shows|has|holds|reflects|contains|currently has|"
        r"is (?:currently )?(?:showing|active|open|restricted|locked|frozen|flagged|under|in|"
        r"on|marked|subject)|was (?:flagged|restricted|frozen|locked))"
    ),
    "i_see_record": (
        r"\b(?:I|we) (?:can |do )?(?:see|found|find|located|have located|pulled up|"
        r"am looking at|'m looking at|’m looking at|have on file|show) "
        r"(?:the |your |his |her |their |a |an |that |this )?(?:\$[\d,]+ )?"
        rf"(?:{RECORD_NOUNS})"
    ),
    "confirm_record": (
        r"\b(?:I|we) (?:can |do )?confirm (?:that )?(?:the |your |his |her |their |this |a )"
        r"(?:\$[\d,]+ )?(?:account|transfer|transaction|order|balance|deposit|trade|position|wire|"
        r"call|payment|withdrawal|debit)"
    ),
    "record_status": (
        r"\b(?:your|his|her|their|the) (?:\$[\d,]+ )?(?:order|trade|transfer|deposit|withdrawal|wire|"
        r"ach|payment|debit|transaction|margin call|call) (?:was|has been|is|went|did|got|"
        r"has|shows as|appears|looks) (?:already |still |now |just |successfully |actually )?"
        r"(?:filled|executed|cancel+ed|rejected|pending|completed|processed|sent|received|returned|"
        r"settled|posted|reversed|approved|denied|declined|in progress|through|out|gone|"
        r"cleared|bounced|due|for \$|partially|outstanding|open|stuck|on hold|held)"
    ),
    "call_amount_or_due": (
        r"\b(?:your|the|his|her) (?:margin |maintenance |reg[- ]t |house )?call (?:is|was|amounts? to|"
        r"totals?|comes to|of \$|for \$|stands at)"
    ),
}

POLARITY_FREE = {
    "account_state_negated": (
        r"\b(?:your|his|her|their) account (?:is|isn't|isn’t|is not) (?:currently )?(?:not )?"
        r"(?:restricted|flagged|frozen|locked|under a call|in a call|in good standing)"
    ),
}

_EMBEDDED_QUESTION = re.compile(r"\b(?:whether|if)\b", re.IGNORECASE)
_SCALE = re.compile(r"(?:k|K|thousand)$")


def amounts(text: str, pattern: re.Pattern = NUMBER) -> set[str]:
    out = set()
    for m in pattern.finditer(text):
        raw = m.group(0).strip()
        scale = 1000 if _SCALE.search(raw) else 1
        base = normalize_money(_SCALE.sub("", raw))
        try:
            out.add(normalize_money(f"{float(base) * scale:.2f}"))
        except ValueError:
            out.add(base)
    return out


@register_detector("disclosure")
class Disclosure(Detector):
    def __init__(self, pack, options):
        super().__init__(pack, options)
        self.masked_field = options.get("masked_field", "account_masked")
        self.assertions = compile_named({**ASSERTIONS, **options.get("extra_assertions", {})})
        self.polarity_free = compile_named({**POLARITY_FREE, **options.get("extra_polarity_free", {})})

    def detect(self, inp: DetectorInput) -> list[Hit]:
        hits: list[Hit] = []
        customer = " ".join(inp.customer_texts)
        allowed = amounts(customer) | set(self.pack.policy_money_amounts)
        for sent in sentences(inp.reply):
            for clause in clauses(sent):
                for m in MONEY.finditer(clause):
                    amt = next(iter(amounts(m.group(0), MONEY)), None)
                    if amt in allowed or negated_before(clause, m.start()):
                        continue
                    hits.append(Hit("amount_not_from_customer", m.group(0)))
                question = is_question(clause)
                for name, rx in self.assertions:
                    for m in rx.finditer(clause):
                        if (
                            question
                            or negated_before(clause, m.start())
                            or _EMBEDDED_QUESTION.search(clause[: m.start()])
                        ):
                            continue
                        hits.append(Hit(name, clause[m.start() : m.end() + 40]))
                for name, rx in self.polarity_free:
                    for m in rx.finditer(clause):
                        hits.append(Hit(name, clause[m.start() : m.end() + 40]))
        masked = inp.context.get(self.masked_field)
        if masked:
            last4 = re.sub(r"\D", "", str(masked))[-4:]
            pat = rf"(?<!\d){last4}(?!\d)"
            if last4 and re.search(pat, inp.reply) and not re.search(pat, customer):
                hits.append(Hit("account_last_four", last4))
        return hits
