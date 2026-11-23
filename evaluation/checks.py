"""Red-flag recall, contradictions, verdict agreement, length and structure.

Red-flag mentions are found with keyword patterns per flag. This is crude: a pattern can hit on a sentence that says
the opposite, and a summary can describe a flag in words no pattern expects. A simple negation guard ("no", "not",
"without" just before the hit) removes the most common false hit. The report hand-checks a sample of hits and misses
(by the agent, labelled as such) to estimate how often the patterns are wrong.
"""

import re
from dataclasses import dataclass

from evaluation.numbers import strip_markdown
from summarizer.facts import FactsSheet

FLAG_PATTERNS: dict[str, list[str]] = {
    "STATUS_NOT_ACTIVE": [
        r"winding[- ]up(?![- ]petition)(?!\s+petitions?)",
        r"being wound up",
        r"liquidation",
        r"not active",
        r"inactive",
    ],
    "WINDING_UP_PETITION": [r"winding[- ]up petitions?", r"petitions? to wind"],
    "NON_CLEAN_AUDIT": [
        r"disclaimer",
        r"going concern",
        r"\bqualified (audit )?opinion",
        r"adverse opinion",
        r"material uncertainty",
        r"audit (qualification|issue|concern)",
    ],
    "NEGATIVE_EQUITY": [
        r"negative (total |shareholders'? )?equity",
        r"liabilities exceed(ed|ing)? (total )?assets",
        r"shareholders'? deficit",
        r"capital deficiency",
        r"equity(?:[^.\n]|\.(?=\d)){0,30}(negative|deficit|-RM|-\s?\d)",
    ],
    "DEFENDANT_JUDGMENT": [r"judge?ments?"],
    "DEFENDANT_PENDING": [
        r"pending",
        r"ongoing",
        r"unresolved",
        r"(open|active|outstanding) (court )?(case|claim|suit|litigation|dispute)",
    ],
    "NET_LOSS": [
        r"net loss",
        r"\bloss(es)?\b",
        r"loss-making",
        r"unprofitable",
        r"profit after tax(?:[^.\n]|\.(?=\d)){0,20}-",
    ],
    "REVENUE_DECLINE": [
        r"(revenue|sales|turnover)(?:[^.\n]|\.(?=\d)){0,60}(fell|fall|declin|drop|decreas|down|lower|shr[ai]nk|contract)",
        r"(fell|fall|declin|drop|decreas|lower)\w*(?:[^.\n]|\.(?=\d)){0,40}(revenue|sales|turnover)",
    ],
    "NEGATIVE_OPERATING_CASH_FLOW": [
        r"(negative|outflow)(?:[^.\n]|\.(?=\d)){0,30}(operating )?cash",
        r"operating cash(?:[^.\n]|\.(?=\d)){0,40}(negative|outflow|-RM|-\s?\d)",
        r"cash burn|burning cash",
    ],
    "WEAK_LIQUIDITY": [
        r"\b(weak|low|poor|tight|strain|thin|limited)\w*(?:[^.\n]|\.(?=\d)){0,30}(liquidity|quick ratio)",
        r"liquidity risk",
        r"(liquidity|quick ratio)(?:[^.\n]|\.(?=\d)){0,40}(?<![a-z])(weak|low|below 1|under 1|tight|concern|pressure|strain|less than 1)",
    ],
    "DEBT_SERVICE_STRAIN": [
        r"(interest cover|interest coverage|debt service|debt-service|dscr|icr)(?:[^.\n]|\.(?=\d)){0,60}"
        r"(?<![a-z])(below|weak|low|negative|under|insufficient|strain|not cover|-\d)",
        r"\b(weak|low|negative|insufficient|strain)\w*(?:[^.\n]|\.(?=\d)){0,40}(interest cover|debt service|debt-service|debt servic)",
        r"(cannot|unable to|not enough to|insufficient to) (cover|service|meet)",
    ],
    "HIGH_LEVERAGE": [
        r"\b(high|heavy|elevated|significant)\w*(?:[^.\n]|\.(?=\d)){0,20}(leverage|gearing|debt|liabilities)",
        r"(leverage|gearing|liabilities(?:[^.\n]|\.(?=\d)){0,20}equity)(?:[^.\n]|\.(?=\d)){0,40}(high|\d+(\.\d+)?x|times)",
        r"highly leveraged",
    ],
    "NO_FINANCIALS": [
        r"no financial",
        r"financials? (are |were )?(not|un)available",
        r"no (financial )?statements",
        r"not filed",
        r"no accounts",
        r"financial (data|information|statements?) (is |are )?(missing|unavailable|not (provided|available))",
    ],
    "RECENT_DIRECTOR_APPOINTMENT": [r"appointed", r"new director", r"joined"],
    "RECENT_NAME_CHANGE": [r"formerly", r"former name", r"renamed", r"name change", r"changed (its )?name", r"previously (known|named|called)"],
    "YOUNG_COMPANY": [
        r"incorporated (in |on )?(20(23|24|25))",
        r"\byoung\b",
        r"recently (incorporated|established|formed)",
        r"new(ly)? (incorporated|established|formed)",
        r"\b[0-2] years? old",
    ],
    "SHORT_HISTORY": [
        r"only (one|1|a single)(?:[^.\n]|\.(?=\d)){0,30}(year|fy)",
        r"single (financial )?year",
        r"one year of",
        r"only fy\s?20\d\d",
        r"no trend",
        r"limited (financial )?history",
    ],
    "MISSING_YEAR": [r"missing", r"no fy\s?20\d\d", r"\bgap\b", r"not available for fy"],
    "DEFENDANT_CASES_CLOSED": [r"settled", r"dismissed", r"withdrawn", r"closed"],
}

NEGATION = re.compile(r"\b(no|not|without|never|nor)\b(?:[^.\n]|\.(?=\d)){0,12}$", flags=re.IGNORECASE)


def find_flag(flag_id: str, text: str) -> str | None:
    """Return the matched snippet if the summary mentions the flag, else None."""
    low = strip_markdown(text).lower()
    for pat in FLAG_PATTERNS[flag_id]:
        for m in re.finditer(pat, low, flags=re.IGNORECASE):
            if NEGATION.search(low[max(0, m.start() - 25) : m.start()]):
                continue
            return low[max(0, m.start() - 40) : m.end() + 40].replace("\n", " ")
    return None


CONTRADICTIONS = [
    # (name, applies(facts), pattern)
    (
        "says no litigation but company is a defendant",
        lambda fs, c: any(x["role"] == "defendant" for x in c["litigation"]["cases"]),
        r"\bno (known |recorded |reported )?(court cases|litigation|legal (cases|issues|proceedings)|lawsuits|disputes)"
        r"|free of litigation|clean litigation",
    ),
    (
        "says profitable but latest year is a loss",
        lambda fs, c: any(f.id == "NET_LOSS" for f in fs.flags),
        r"(?<!un)\bprofitable\b|\bremained in profit|\bis in profit",
    ),
    (
        "says active but status is not active",
        lambda fs, c: c["profile"]["status"] != "Active",
        r"(status(?:[^.\n]|\.(?=\d)){0,12}\bactive\b)|\bis active\b|\bactive company\b",
    ),
    (
        "says positive or healthy equity but equity is negative",
        lambda fs, c: any(f.id == "NEGATIVE_EQUITY" for f in fs.flags),
        r"(positive|healthy|strong) (total )?equity",
    ),
    (
        "says all audits clean but one is not",
        lambda fs, c: any(f.id == "NON_CLEAN_AUDIT" for f in fs.flags),
        r"all(?:[^.\n]|\.(?=\d)){0,25}(unqualified|clean)|(unqualified|clean) (audit )?opinions? (in|for|across) all|consistently (unqualified|clean)",
    ),
]


def contradictions(text: str, fs: FactsSheet, company: dict) -> list[str]:
    low = strip_markdown(text).lower()
    out = []
    for name, applies, pat in CONTRADICTIONS:
        if not applies(fs, company):
            continue
        for m in re.finditer(pat, low):
            if NEGATION.search(low[max(0, m.start() - 25) : m.start()]):
                continue
            out.append(f"{name}: '...{low[max(0, m.start() - 30) : m.end() + 30].strip()}...'")
            break
    return out


SECTION_LABELS = ["verdict:", "key risks:", "financials:", "people and ownership:", "data gaps:"]
TRIAGE_LEVELS = ["high concern", "review", "low concern"]


def word_count(text: str) -> int:
    return len([w for w in strip_markdown(text).split() if re.search(r"\w", w)])


def structure_ok(text: str) -> tuple[bool, list[str]]:
    low = text.lower().replace("*", "")
    pos = [low.find(label) for label in SECTION_LABELS]
    missing = [SECTION_LABELS[i] for i, p in enumerate(pos) if p < 0]
    in_order = not missing and pos == sorted(pos)
    return in_order, missing


def stated_verdict(text: str) -> str | None:
    m = re.search(r"verdict:\s*([a-z ]+)", text.lower().replace("*", ""))
    if not m:
        return None
    head = m.group(1).strip()
    return next((lvl for lvl in TRIAGE_LEVELS if head.startswith(lvl)), None)


@dataclass
class FlagResult:
    flag_id: str
    severity: str
    hit: str | None


def flag_results(text: str, fs: FactsSheet) -> list[FlagResult]:
    seen = set()
    out = []
    for f in fs.flags:
        if f.id in seen:
            continue
        seen.add(f.id)
        out.append(FlagResult(f.id, f.severity, find_flag(f.id, text)))
    return out


FINANCIALS_LABELS = ("revenue", "profit", "equity", "quick")


def financials_labelled(text: str) -> bool | None:
    """Structured versions only: does the Financials line name what each number is? None if there is no such line."""
    m = re.search(r"financials[^:\n]*:(.*)", text.replace("*", ""), flags=re.IGNORECASE)
    if not m:
        return None
    line = m.group(1).lower()
    return all(label in line for label in FINANCIALS_LABELS)
