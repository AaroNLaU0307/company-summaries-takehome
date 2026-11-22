"""Number traceability: is every number in a summary in the record (or computed directly from it)?

How it works
1. Extract numbers from the summary text, skipping identifiers (SYN-, CASE-), dates, FY labels, bare years and
   placeholder names ("Director 3", "Audit Firm 8").
2. Classify each number: money (has RM or a unit such as m / million / k), percent, ratio (decimal, or ends in x),
   count (bare integer).
3. Build candidate values from the record: every numeric field, ratios as percentages, counts of cases / directors /
   shareholders / years, sums of claim amounts, and percentage changes of each statement line between years.
4. A number matches a candidate if they agree to the precision the summary displays: "RM 5.35m" matches
   5,352,856 because 5.352856 rounds to 5.35; "30%" matches 0.3007. Signs are ignored ("fell 7.4%" vs -7.4).

Known limits (measured in the report): a lenient match can accept a wrong number that happens to equal some other
field ("coincidental match"). The negative control (score a summary against a different company's record) estimates
how often that happens.
"""

import itertools
import re
from dataclasses import dataclass

from summarizer.facts import build_facts

UNIT = {"m": 1e6, "mn": 1e6, "mil": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3, "bn": 1e9, "billion": 1e9}

SKIP_PATTERNS = [
    r"SYN-\d+",
    r"CASE-\d{4}-\d+",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
    r"\bFY\s?'?\d{2,4}\b",
    r"\b(?:Director|Shareholder|Audit Firm|Firm)\s+\d+\b",
    r"\bQ[1-4]\b",
]
SKIP_RE = re.compile("|".join(SKIP_PATTERNS), flags=re.IGNORECASE)

NUM_RE = re.compile(
    r"(?P<neg>[-−]\s?)?(?P<rm>(?:RM|MYR)\s?)?(?P<neg2>[-−])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<unit>\s?(?:million|billion|thousand|mil|mn|bn|m|k)\b)?(?P<pct>\s?%|\s?percent\b)?(?P<x>x\b|\s?times\b)?",
    flags=re.IGNORECASE,
)


@dataclass
class Num:
    text: str
    kind: str  # money | percent | ratio | count
    value: float
    decimals: int
    scale: float
    start: int
    end: int


@dataclass
class Match:
    num: Num
    matched: bool
    path: str | None
    context: str


def strip_markdown(text: str) -> str:
    t = re.sub(r"[*_`#|]", " ", text)
    t = re.sub(r"^\s*[-+]\s+", " ", t, flags=re.MULTILINE)
    return re.sub(r"^\s*\d+[.)]\s+", " ", t, flags=re.MULTILINE)  # numbered list markers


def extract_numbers(text: str) -> list[Num]:
    t = strip_markdown(text)
    masked = SKIP_RE.sub(lambda m: " " * len(m.group(0)), t)
    out: list[Num] = []
    for m in NUM_RE.finditer(masked):
        raw = m.group("num")
        # Skip pieces glued to letters (e.g. "B2B", "4G"), except a unit suffix which the regex already captured.
        if m.start("num") > 0 and masked[m.start("num") - 1].isalpha() and not m.group("rm"):
            continue
        value = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        unit = (m.group("unit") or "").strip().lower()
        scale = UNIT.get(unit, 1.0)
        if m.group("pct"):
            kind = "percent"
        elif m.group("rm") or unit:
            kind = "money"
        elif m.group("x") or decimals > 0:
            kind = "ratio"
        else:
            # Bare integer: a year, a count, or a full RM amount written without "RM".
            if 1950 <= value <= 2030 and decimals == 0 and "," not in raw:
                continue
            kind = "money" if value >= 1000 else "count"
        out.append(Num(t[m.start() : m.end()].strip(), kind, value, decimals, scale, m.start(), m.end()))
    return out


def _walk(obj, path=""):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        yield path, float(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def candidates(company: dict) -> dict[str, list[tuple[str, float]]]:
    """Candidate values by kind. Values are absolute (signs ignored)."""
    money: list[tuple[str, float]] = []
    pct: list[tuple[str, float]] = []
    ratio: list[tuple[str, float]] = []
    count: list[tuple[str, float]] = []
    years = sorted(company["financials"]["years"], key=lambda y: y["financialYear"])
    for path, v in _walk(company):
        if path.endswith("financialYear"):
            continue
        if ".ratiosAndMetrics." in path or path.startswith("financials.years") and "ratiosAndMetrics" in path:
            ratio.append((path, abs(v)))
            pct.append((path + " x100", abs(v) * 100))
            money.append((path, abs(v)))  # ebitda, operatingCashFlow, netWorkingCapital are amounts
        elif path.endswith("percentage"):
            pct.append((path, abs(v)))
        else:
            money.append((path, abs(v)))
            if abs(v) < 1000 and float(v).is_integer():
                count.append((path, abs(v)))
    # Derived from the facts sheet (counts, sums, changes)
    fs = build_facts(company)
    for k, v in fs.derived_numbers.items():
        (pct if k.endswith("_pct") else money if v >= 1000 else count).append((f"facts.{k}", abs(v)))
    # Thresholds the facts sheet states ("quick ratio below 1.0", "fell at least 10%")
    ratio += [("threshold.quick_ratio", 1.0), ("threshold.interest_coverage", 1.5), ("threshold.leverage", 2.0)]
    pct += [("threshold.revenue_decline", 10.0)]
    # Shares of ownership combined, and sums of up to all shareholders (e.g. "directors hold 79.47%")
    shs = [s["percentage"] for s in company["relationships"]["shareholders"]]
    for r in range(2, len(shs) + 1):
        for combo in itertools.combinations(range(len(shs)), r):
            pct.append((f"shareholders.sum{combo}", sum(shs[i] for i in combo)))
    # Percentage changes of statement lines between any two years; ratio changes in points.
    for a, b in itertools.combinations(years, 2):
        for key in a["statements"]:
            va, vb = a["statements"][key], b["statements"][key]
            if va:
                pct.append((f"change.{key}.FY{a['financialYear']}-FY{b['financialYear']}", abs((vb / va - 1) * 100)))
            money.append((f"diff.{key}.FY{a['financialYear']}-FY{b['financialYear']}", abs(vb - va)))
        for group, metrics in a["ratiosAndMetrics"].items():
            for key, va in metrics.items():
                vb = b["ratiosAndMetrics"][group][key]
                if va is not None and vb is not None:
                    pct.append((f"points.{key}.FY{a['financialYear']}-FY{b['financialYear']}", abs((vb - va) * 100)))
    # Counts that a reader would naturally state
    cases = company["litigation"]["cases"]
    groups: dict[str, int] = {}
    for c in cases:
        for key in (c["role"], c["status"], c["caseType"], f"{c['role']}|{c['status']}", f"{c['role']}|{c['caseType']}"):
            groups[key] = groups.get(key, 0) + 1
    for key, n in groups.items():
        count.append((f"cases.count.{key}", n))
    for role in ("defendant", "plaintiff"):
        for status_set_name, status_set in {
            "open": ("Pending", "Judgment entered"),
            "closed": ("Settled", "Dismissed", "Withdrawn"),
        }.items():
            sel = [c for c in cases if c["role"] == role and c["status"] in status_set]
            count.append((f"cases.count.{role}.{status_set_name}", len(sel)))
            money.append((f"cases.sum.{role}.{status_set_name}", sum(c["claimAmount"] for c in sel)))
    count += [("count.years", len(years)), ("count.formerNames", len(company["profile"]["formerNames"]))]
    count += [("count.directors", len(company["relationships"]["directors"]))]
    count += [("count.shareholders", len(company["relationships"]["shareholders"]))]
    # Age of the company in years, and the number of years since each director appointment, as of the record date
    inc = int(company["profile"]["incorporationDate"][:4])
    count += [("age.company", 2025 - inc), ("age.company+1", 2026 - inc)]
    return {"money": money, "percent": pct, "ratio": ratio, "count": count}


def _close(display: float, decimals: int, value: float) -> bool:
    return abs(abs(display) - value) <= 0.5 * 10 ** (-decimals) + 1e-9


def match_number(n: Num, cands: dict[str, list[tuple[str, float]]]) -> str | None:
    if n.kind == "money":
        pools = [("money", n.scale)]
        if n.scale == 1.0 and n.value < 1000:
            pools.append(("count", 1.0))
    elif n.kind == "percent":
        pools = [("percent", 1.0)]
    elif n.kind == "ratio":
        pools = [("ratio", 1.0)]
    else:
        pools = [("count", 1.0), ("money", 1.0)]
    for pool, scale in pools:
        for path, v in cands[pool]:
            if _close(n.value, n.decimals, v / scale):
                return path
    return None


def sentence_around(text: str, start: int, end: int) -> str:
    t = strip_markdown(text)
    left = max(t.rfind(".", 0, max(start - 1, 0)), t.rfind("\n", 0, start))
    right_candidates = [i for i in (t.find(". ", end), t.find("\n", end)) if i != -1]
    right = min(right_candidates) if right_candidates else len(t)
    return " ".join(t[left + 1 : right + 1].split())[:220]


def check_summary(summary: str, company: dict) -> list[Match]:
    cands = candidates(company)
    return [
        Match(n, (path := match_number(n, cands)) is not None, path, sentence_around(summary, n.start, n.end))
        for n in extract_numbers(summary)
    ]
