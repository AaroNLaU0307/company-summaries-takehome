"""Tests for the facts sheet and the evaluation checks, using hand-written dummy summaries (not model output)."""

from evaluation.checks import contradictions, flag_results, stated_verdict, structure_ok, word_count
from evaluation.numbers import check_summary, extract_numbers
from summarizer.data import companies_by_id
from summarizer.facts import build_facts
from summarizer.generate import normalise

C = companies_by_id()

# Hand-written, faithful, in the v2 structure. SYN-000451: negative equity, loss, weak liquidity.
GOOD_451 = """**Verdict:** High concern: negative equity of -RM 18.5k in FY2024 and a second year of losses.

**Key risks:**
- Negative equity of -RM 18.5k in FY2024: liabilities exceed assets.
- Net loss of RM 275.6k in FY2024 (FY2023: loss of RM 267.2k).
- Negative operating cash flow of RM 138.9k.
- Weak liquidity: quick ratio 0.63, below 1.0.
- Interest coverage -5.37x, below 1.5.

**Financials:** FY2024 revenue RM 2.08m, down 7.4% on FY2023. Net margin -13.2%.

**People and ownership:** 5 directors. Director 1 holds 50.59%. Name changed on 2025-11-27 (formerly Gemilang Ventures Sdn. Bhd.).

**Data gaps:** None."""

# Same shape, with planted errors: wrong revenue, invented percentage, a claim of profitability, missing flags.
BAD_451 = """**Verdict:** Low concern: a profitable bakery.

**Key risks:**
- None found in the record.

**Financials:** FY2024 revenue RM 3.9m, up 12.5%. Equity is healthy.

**People and ownership:** 5 directors.

**Data gaps:** None."""


def test_facts_flags_451():
    fs = build_facts(C["SYN-000451"])
    ids = {f.id for f in fs.flags}
    assert fs.triage == "High concern"
    assert {"NEGATIVE_EQUITY", "NET_LOSS", "WEAK_LIQUIDITY", "NEGATIVE_OPERATING_CASH_FLOW"} <= ids
    assert "HIGH_LEVERAGE" not in ids  # suppressed when equity is negative
    assert fs.key_numbers["latest_liabilities_to_equity"] is None


def test_facts_status_outranks_profit():
    fs = build_facts(C["SYN-000545"])  # winding up but profitable
    assert fs.triage == "High concern"
    assert fs.flags[0].id == "STATUS_NOT_ACTIVE"
    assert any(f.id == "NON_CLEAN_AUDIT" and "FY2022" in f.text for f in fs.flags)


def test_facts_gaps():
    assert any(f.id == "NO_FINANCIALS" for f in build_facts(C["SYN-000302"]).flags)
    assert any(f.id == "MISSING_YEAR" for f in build_facts(C["SYN-000286"]).flags)
    assert any(f.id == "SHORT_HISTORY" for f in build_facts(C["SYN-001298"]).flags)


def test_extract_skips_ids_dates_years_and_names():
    nums = extract_numbers("SYN-000451 filed CASE-2025-0811 on 2025-09-22 in FY2024 by Director 3 in 2019; RM 1.2m and 15%")
    assert [n.text for n in nums] == ["RM 1.2m", "15%"]


def test_extract_kinds():
    nums = {n.text: n.kind for n in extract_numbers("RM 2.08m, 7.4%, 0.63, -5.37x, 5 directors, 1,234,500")}
    assert nums == {"RM 2.08m": "money", "7.4%": "percent", "0.63": "ratio", "-5.37x": "ratio", "5": "count", "1,234,500": "money"}


def test_good_summary_fully_traceable():
    res = check_summary(GOOD_451, C["SYN-000451"])
    bad = [m.num.text for m in res if not m.matched]
    assert bad == [], bad


def test_bad_summary_numbers_flagged():
    res = check_summary(BAD_451, C["SYN-000451"])
    assert {m.num.text for m in res if not m.matched} == {"RM 3.9m", "12.5%"}


def test_unit_and_rounding_tolerance():
    c = C["SYN-000029"]  # FY2024 revenue 5,352,856; gross margin 0.351
    for text in ("RM 5.35m", "RM 5.4 million", "RM 5,352,856", "RM 5352.9k", "MYR 5.35M", "35.1%", "35%"):
        assert all(m.matched for m in check_summary(text, c)), text
    assert not any(m.matched for m in check_summary("RM 5.29m", c))


def test_negative_control_drops():
    res = check_summary(GOOD_451, C["SYN-000029"])
    material = [m for m in res if m.num.kind != "count"]
    assert sum(m.matched for m in material) < len(material) / 2


def test_flag_recall_good_vs_bad():
    fs = build_facts(C["SYN-000451"])
    good = {f.flag_id: f.hit for f in flag_results(GOOD_451, fs) if f.severity != "low"}
    bad = {f.flag_id: f.hit for f in flag_results(BAD_451, fs) if f.severity != "low"}
    assert all(good.values()), good
    assert not any(bad.values()), bad


def test_negation_guard():
    fs = build_facts(C["SYN-000451"])
    hits = {f.flag_id: f.hit for f in flag_results("The company reported no losses.", fs)}
    assert hits["NET_LOSS"] is None


def test_contradictions():
    fs = build_facts(C["SYN-000451"])
    assert contradictions(BAD_451, fs, C["SYN-000451"])
    assert contradictions(GOOD_451, fs, C["SYN-000451"]) == []
    fs2 = build_facts(C["SYN-000286"])
    assert contradictions("There is no litigation on record.", fs2, C["SYN-000286"])


def test_structure_length_verdict():
    assert structure_ok(GOOD_451)[0]
    assert not structure_ok("A company that sells cakes.")[0]
    assert stated_verdict(GOOD_451) == "high concern"
    assert stated_verdict(BAD_451) == "low concern"
    assert 80 <= word_count(GOOD_451) <= 150


def test_normalise():
    assert normalise("```markdown\nA " + chr(0x2014) + " B\n```") == "A, B"


def test_patterns_span_decimals():
    fs = build_facts(C["SYN-000451"])
    hits = {f.flag_id: f.hit for f in flag_results("Quick ratio 0.63 in FY2024 (below 1.0).", fs)}
    assert hits["WEAK_LIQUIDITY"]
