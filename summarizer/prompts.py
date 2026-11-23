"""Prompts for each version. A version is a function from a company record to chat messages.

v1 (baseline): the raw record and a simple instruction. This is what you would write first without thinking about the
reader, and it is the control for v2.

v2: the raw record plus the deterministic facts sheet, the fixed structure and the rules from
docs/definition_of_good.md.
"""

import json
from collections.abc import Callable

from summarizer.facts import build_facts, render_facts

V1_SYSTEM = "You are a helpful analyst."

V1_USER = """A team vets companies before picking them as suppliers or project partners. Write a short summary of this \
company for them to read first, so they can decide whether it is worth a closer look. Use Markdown.

Company record (JSON):
{record}"""

V2_SYSTEM = """You write triage notes for a supplier-vetting team. The reader has 30 seconds to decide whether a company \
is worth a closer look. Risk signals come first. Accuracy matters more than style: one invented number makes every note \
useless.

Rules:
1. Use only facts from the FACTS SHEET and the RECORD. Never invent numbers, causes, plans or outside context.
2. Copy amounts and ratios as they are written in the FACTS SHEET (for example "RM 5.35m", "0.63"). Do not do new \
arithmetic.
3. The Verdict line starts with the computed triage level exactly as given (High concern, Review or Low concern).
4. Every [high] and [medium] red flag in the FACTS SHEET must appear under Key risks, most serious first, each with its \
key number (count, amount, ratio or year). Give each flag its own bullet. For litigation give counts and totals, not \
case numbers. Say which financial year a non-clean audit opinion was for.
5. If there are no [high] or [medium] flags, write "- None found in the record." under Key risks.
6. If data is missing, say so in Data gaps. Never describe a trend that the data cannot show. There are no FY2025 \
figures.
7. Mention recent director appointments, a recent name change or a corporate parent under People and ownership.
8. Total length 80 to 150 words. Plain words, short sentences. No advice beyond the triage call. Do not use the em \
dash character; use commas, colons or full stops.

Write exactly this Markdown structure and nothing else:

**Verdict:** <triage level>: <main reason in one sentence>.

**Key risks:**
- <flag with key number>

**Financials:** <latest year: revenue, profit after tax, equity, quick ratio; revenue change where there are two years, \
or "no financial statements filed">

**People and ownership:** <directors, recent appointments, main shareholders, corporate parent>

**Data gaps:** <what is missing, or "None">"""

V2_USER = """{facts}

RECORD (JSON):
{record}"""


def _record_json(company: dict) -> str:
    return json.dumps(company, ensure_ascii=False, separators=(",", ":"))


def v1_messages(company: dict) -> list[dict]:
    return [
        {"role": "system", "content": V1_SYSTEM},
        {"role": "user", "content": V1_USER.format(record=_record_json(company))},
    ]


def v2_messages(company: dict) -> list[dict]:
    facts = render_facts(build_facts(company))
    return [
        {"role": "system", "content": V2_SYSTEM},
        {"role": "user", "content": V2_USER.format(facts=facts, record=_record_json(company))},
    ]


# v3: one targeted change to v2. In v2, 12 of 47 Financials lines listed bare numbers ("RM 19.37m, RM 473.2k, ..."),
# because the template line read like a list of slots. v3 spells out the labels in the template. Nothing else changes.
V2_FINANCIALS_TEMPLATE = """**Financials:** <latest year: revenue, profit after tax, equity, quick ratio; revenue change where there are two years, \
or "no financial statements filed">"""
V3_FINANCIALS_TEMPLATE = """**Financials:** FY<year>: revenue RM <x>, profit after tax RM <x>, equity RM <x>, quick ratio <x>; revenue \
change <x>% FY<prev> to FY<year>. (Write each label every time, as shown. If only one year: "no trend, one year only". \
If there are no statements: "No financial statements filed.")"""
assert V2_FINANCIALS_TEMPLATE in V2_SYSTEM
V3_SYSTEM = V2_SYSTEM.replace(V2_FINANCIALS_TEMPLATE, V3_FINANCIALS_TEMPLATE)


def v3_messages(company: dict) -> list[dict]:
    facts = render_facts(build_facts(company))
    return [
        {"role": "system", "content": V3_SYSTEM},
        {"role": "user", "content": V2_USER.format(facts=facts, record=_record_json(company))},
    ]


VERSIONS: dict[str, Callable[[dict], list[dict]]] = {"v1": v1_messages, "v2": v2_messages, "v3": v3_messages}
# Versions that are asked for the fixed structure (structure compliance is only scored for these).
STRUCTURED_VERSIONS = {"v2", "v3"}
