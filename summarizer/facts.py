"""Deterministic facts sheet per company: red flags, triage level and key numbers.

Plain Python, no LLM. The rules are the ones written in docs/definition_of_good.md before any generation. The output is
used twice: as input to the v2 prompt, and as the ground truth the evaluation scores every version against.

Run `uv run python -m summarizer.facts SYN-000545` to print one sheet, or with no argument to print a flag table.
"""

import sys
from dataclasses import asdict, dataclass, field

from summarizer.data import RECORD_DATE, load_companies

RECENT_DIRECTOR_FROM = "2025-01-01"
RECENT_NAME_CHANGE_FROM = "2024-01-01"
YOUNG_COMPANY_FROM = "2023-01-01"

REVENUE_DECLINE_THRESHOLD = -0.10
QUICK_RATIO_MIN = 1.0
INTEREST_COVERAGE_MIN = 1.5
DSCR_MIN = 1.0
LEVERAGE_MAX = 2.0

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
MATERIAL = ("high", "medium")


@dataclass
class Flag:
    id: str
    severity: str
    text: str


@dataclass
class FactsSheet:
    registration_number: str
    company_name: str
    triage: str
    flags: list[Flag]
    key_numbers: dict[str, object]
    data_gaps: list[str]
    # Every number this sheet states (counts, sums, changes), so the traceability check can accept them.
    derived_numbers: dict[str, float] = field(default_factory=dict)

    def material_flags(self) -> list[Flag]:
        return [f for f in self.flags if f.severity in MATERIAL]

    def to_dict(self) -> dict:
        return asdict(self)


def fmt_rm(amount: float) -> str:
    """RM with a unit: RM 5.35m, RM 97.6k, RM 850."""
    sign = "-" if amount < 0 else ""
    a = abs(amount)
    if a >= 1e9:
        return f"{sign}RM {a / 1e9:.2f}bn"
    if a >= 1e6:
        return f"{sign}RM {a / 1e6:.2f}m"
    if a >= 1e3:
        return f"{sign}RM {a / 1e3:.1f}k"
    return f"{sign}RM {a:.0f}"


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _cases_text(cases: list[dict]) -> str:
    return "; ".join(
        f"{c['caseNumber']} {c['caseType'].lower()}, filed {c['filedOn']}, {c['status'].lower()}, claim {fmt_rm(c['claimAmount'])}"
        for c in cases
    )


def build_facts(company: dict) -> FactsSheet:
    reg = company["registrationNumber"]
    p = company["profile"]
    rel = company["relationships"]
    years = sorted(company["financials"]["years"], key=lambda y: y["financialYear"])
    cases = company["litigation"]["cases"]
    flags: list[Flag] = []
    gaps: list[str] = []
    derived: dict[str, float] = {}
    key: dict[str, object] = {
        "status": p["status"],
        "industry": p["industry"],
        "state": p["state"],
        "incorporated": p["incorporationDate"],
        "share_capital": fmt_rm(p["shareCapital"]),
    }

    # Status
    if p["status"] != "Active":
        flags.append(Flag("STATUS_NOT_ACTIVE", "high", f"Company status is '{p['status']}' (not Active)."))

    # Litigation: only defendant cases are risk.
    defendant = [c for c in cases if c["role"] == "defendant"]
    plaintiff = [c for c in cases if c["role"] == "plaintiff"]
    wup = [c for c in defendant if c["caseType"] == "Winding-up petition"]
    other = [c for c in defendant if c["caseType"] != "Winding-up petition"]
    judgment = [c for c in other if c["status"] == "Judgment entered"]
    pending = [c for c in other if c["status"] == "Pending"]
    closed = [c for c in other if c["status"] in ("Settled", "Dismissed", "Withdrawn")]
    derived.update(
        {
            "cases_total": len(cases),
            "cases_defendant": len(defendant),
            "cases_plaintiff": len(plaintiff),
            "cases_defendant_claims_total": sum(c["claimAmount"] for c in defendant),
            "cases_plaintiff_claims_total": sum(c["claimAmount"] for c in plaintiff),
        }
    )
    if wup:
        derived["winding_up_petitions"] = len(wup)
        derived["winding_up_claims_total"] = sum(c["claimAmount"] for c in wup)
        open_wup = [c for c in wup if c["status"] in ("Pending", "Judgment entered")]
        derived["winding_up_open"] = len(open_wup)
        flags.append(
            Flag(
                "WINDING_UP_PETITION",
                "high",
                f"Defendant in {len(wup)} winding-up petition(s), {len(open_wup)} pending or with judgment entered: "
                + _cases_text(wup)
                + ".",
            )
        )
    if judgment:
        total = sum(c["claimAmount"] for c in judgment)
        derived["judgments_against"] = len(judgment)
        derived["judgments_against_total"] = total
        flags.append(
            Flag(
                "DEFENDANT_JUDGMENT",
                "high",
                f"Judgment entered against the company in {len(judgment)} case(s), claims totalling {fmt_rm(total)}: "
                + _cases_text(judgment)
                + ".",
            )
        )
    if pending:
        total = sum(c["claimAmount"] for c in pending)
        derived["pending_against"] = len(pending)
        derived["pending_against_total"] = total
        flags.append(
            Flag(
                "DEFENDANT_PENDING",
                "medium",
                f"{len(pending)} pending case(s) against the company, claims totalling {fmt_rm(total)}: "
                + _cases_text(pending)
                + ".",
            )
        )
    if closed:
        total = sum(c["claimAmount"] for c in closed)
        derived["closed_against"] = len(closed)
        derived["closed_against_total"] = total
        flags.append(
            Flag(
                "DEFENDANT_CASES_CLOSED",
                "low",
                f"{len(closed)} closed case(s) against the company (settled, dismissed or withdrawn), claims totalling "
                f"{fmt_rm(total)}.",
            )
        )
    key["litigation"] = (
        f"{len(cases)} case(s): {len(defendant)} as defendant, {len(plaintiff)} as plaintiff"
        if cases
        else "No court cases on record"
    )

    # Audit: every year.
    bad_audits = [y for y in years if y["audit"]["opinion"] != "Unqualified"]
    if bad_audits:
        flags.append(
            Flag(
                "NON_CLEAN_AUDIT",
                "high",
                "Non-clean audit opinion: "
                + "; ".join(f"FY{y['financialYear']} '{y['audit']['opinion']}' ({y['audit']['firm']})" for y in bad_audits)
                + ".",
            )
        )

    # Financials
    if not years:
        flags.append(Flag("NO_FINANCIALS", "medium", "No financial statements in the record; cannot assess finances."))
        gaps.append("No financial statements filed.")
    else:
        fys = [y["financialYear"] for y in years]
        key["financial_years"] = ", ".join(f"FY{fy}" for fy in fys)
        latest = years[-1]
        s = latest["statements"]
        m = latest["ratiosAndMetrics"]
        fy = latest["financialYear"]
        key["latest_year"] = f"FY{fy} (year end {latest['financialYearEnd']})"
        key["latest_revenue"] = fmt_rm(s["revenue"])
        key["latest_profit_after_tax"] = fmt_rm(s["profitAfterTax"])
        key["latest_total_equity"] = fmt_rm(s["totalEquity"])
        key["latest_operating_cash_flow"] = fmt_rm(s["operatingCashFlow"])
        key["latest_borrowings"] = fmt_rm(s["borrowings"])
        qr = m["liquidityAndCashFlow"]["quickRatio"]
        icr = m["capitalStructure"]["interestCoverageRatio"]
        dscr = m["capitalStructure"]["debtServiceCoverageRatio"]
        lev = m["capitalStructure"]["leverageRatio"]
        npm = m["profitability"]["netProfitMargin"]
        key["latest_quick_ratio"] = None if qr is None else round(qr, 2)
        key["latest_interest_coverage"] = None if icr is None else round(icr, 2)
        key["latest_debt_service_coverage"] = None if dscr is None else round(dscr, 2)
        key["latest_liabilities_to_equity"] = None if lev is None or s["totalEquity"] < 0 else round(lev, 2)
        key["latest_net_profit_margin"] = None if npm is None else fmt_pct(npm)
        key["audit_opinions"] = "; ".join(f"FY{y['financialYear']} {y['audit']['opinion']}" for y in years)

        if len(years) == 1:
            flags.append(Flag("SHORT_HISTORY", "low", f"Only one year of financial statements (FY{fy}); no trend."))
            gaps.append(f"Only FY{fy} statements; no trend available.")
        missing = [y for y in range(fys[0], fys[-1] + 1) if y not in fys]
        if missing:
            flags.append(
                Flag("MISSING_YEAR", "low", "Missing financial year(s): " + ", ".join(f"FY{y}" for y in missing) + ".")
            )
            gaps.append("Missing " + ", ".join(f"FY{y}" for y in missing) + " statements.")

        if s["totalEquity"] < 0:
            flags.append(
                Flag(
                    "NEGATIVE_EQUITY",
                    "high",
                    f"Negative equity of {fmt_rm(s['totalEquity'])} in FY{fy}: liabilities exceed assets.",
                )
            )
        elif lev is not None and lev > LEVERAGE_MAX:
            flags.append(
                Flag("HIGH_LEVERAGE", "medium", f"High leverage in FY{fy}: liabilities are {lev:.2f}x equity.")
            )
        if s["profitAfterTax"] < 0:
            flags.append(Flag("NET_LOSS", "medium", f"Net loss of {fmt_rm(s['profitAfterTax'])} in FY{fy}."))
        if len(years) >= 2:
            prev = years[-2]
            gap = fy - prev["financialYear"]
            prev_rev = prev["statements"]["revenue"]
            if prev_rev:
                chg = s["revenue"] / prev_rev - 1
                derived["revenue_change_pct"] = round(chg * 100, 2)
                label = f"FY{prev['financialYear']} to FY{fy}" + (" (two-year change, FY in between missing)" if gap > 1 else "")
                key["revenue_change"] = f"{fmt_pct(chg)} {label}"
                if chg <= REVENUE_DECLINE_THRESHOLD:
                    flags.append(
                        Flag(
                            "REVENUE_DECLINE",
                            "medium",
                            f"Revenue fell {fmt_pct(-chg)}, from {fmt_rm(prev_rev)} to {fmt_rm(s['revenue'])}, {label}.",
                        )
                    )
            prev_pat = prev["statements"]["profitAfterTax"]
            key["previous_profit_after_tax"] = f"{fmt_rm(prev_pat)} (FY{prev['financialYear']})"
            if prev_pat:
                derived["pat_change_pct"] = round((s["profitAfterTax"] / prev_pat - 1) * 100, 2)
        if s["operatingCashFlow"] < 0:
            flags.append(
                Flag(
                    "NEGATIVE_OPERATING_CASH_FLOW",
                    "medium",
                    f"Negative operating cash flow of {fmt_rm(s['operatingCashFlow'])} in FY{fy}.",
                )
            )
        if qr is not None and qr < QUICK_RATIO_MIN:
            flags.append(Flag("WEAK_LIQUIDITY", "medium", f"Quick ratio {qr:.2f} in FY{fy} (below 1.0)."))
        strain = []
        if icr is not None and icr < INTEREST_COVERAGE_MIN:
            strain.append(f"interest coverage {icr:.2f}x (below 1.5)")
        if dscr is not None and dscr < DSCR_MIN:
            strain.append(f"debt service coverage {dscr:.2f}x (below 1.0)")
        if strain:
            flags.append(Flag("DEBT_SERVICE_STRAIN", "medium", f"Debt service strain in FY{fy}: " + ", ".join(strain) + "."))

    # People and ownership
    directors = rel["directors"]
    shareholders = sorted(rel["shareholders"], key=lambda x: -x["percentage"])
    recent = [d for d in directors if d["appointedOn"] >= RECENT_DIRECTOR_FROM]
    derived["directors"] = len(directors)
    derived["shareholders"] = len(shareholders)
    derived["recent_directors"] = len(recent)
    key["directors"] = f"{len(directors)} director(s)"
    key["shareholders"] = "; ".join(
        f"{sh['name']} {sh['percentage']:g}%" + (" (company)" if sh["type"] == "company" else "") for sh in shareholders
    )
    if recent:
        flags.append(
            Flag(
                "RECENT_DIRECTOR_APPOINTMENT",
                "low",
                f"{len(recent)} of {len(directors)} director(s) appointed in the last 12 months: "
                + ", ".join(f"{d['name']} ({d['designation']}, {d['appointedOn']})" for d in recent)
                + ".",
            )
        )
    for fn in p["formerNames"]:
        if fn["changedOn"] >= RECENT_NAME_CHANGE_FROM:
            flags.append(
                Flag("RECENT_NAME_CHANGE", "low", f"Name changed on {fn['changedOn']} (formerly {fn['name']}).")
            )
    if p["incorporationDate"] >= YOUNG_COMPANY_FROM:
        flags.append(Flag("YOUNG_COMPANY", "low", f"Young company: incorporated {p['incorporationDate']}."))
    derived["company_age_years"] = int(RECORD_DATE[:4]) - int(p["incorporationDate"][:4])

    flags.sort(key=lambda f: SEVERITY_ORDER[f.severity])
    sev = {f.severity for f in flags}
    triage = "High concern" if "high" in sev else "Review" if "medium" in sev else "Low concern"
    return FactsSheet(reg, p["companyName"], triage, flags, key, gaps or ["None"], derived)


def render_facts(fs: FactsSheet) -> str:
    """Plain-text facts sheet for the prompt."""
    lines = [f"FACTS SHEET (computed by code from the record) for {fs.company_name} ({fs.registration_number})"]
    lines.append(f"Computed triage level: {fs.triage}")
    lines.append("Red flags, most serious first:")
    material = fs.material_flags()
    if material:
        lines += [f"- [{f.severity}] {f.text}" for f in material]
    else:
        lines.append("- None found by the rules.")
    low = [f for f in fs.flags if f.severity == "low"]
    if low:
        lines.append("Context (low severity):")
        lines += [f"- {f.text}" for f in low]
    lines.append("Key numbers:")
    lines += [f"- {k}: {v}" for k, v in fs.key_numbers.items() if v is not None]
    lines.append("Data gaps: " + " ".join(fs.data_gaps))
    return "\n".join(lines)


def all_facts() -> dict[str, FactsSheet]:
    return {c["registrationNumber"]: build_facts(c) for c in load_companies()}


def main() -> None:
    facts = all_facts()
    if len(sys.argv) > 1:
        for reg in sys.argv[1:]:
            print(render_facts(facts[reg]))
            print()
        return
    for reg, fs in facts.items():
        ids = ",".join(f.id for f in fs.material_flags()) or "-"
        print(f"{reg}  {fs.triage:<12}  {ids}")


if __name__ == "__main__":
    main()
