# Manual review results

Scored rows: 20 of 20. Reviewer: a separate Claude agent that did not build the system, blind to version labels; Aaron then reviewed all 20 scores and notes against the records and agreed with them.

| Version | n | faithful_0_2 | red_flags_0_2 | verdict_0_2 | readable_0_2 | total (of 8) |
|---|---|---|---|---|---|---|
| v1 | 10 | 1.20 | 1.50 | 1.50 | 1.10 | 5.30 |
| v3 | 10 | 1.80 | 2.00 | 2.00 | 2.00 | 7.80 |

## Notes

- SYN-000029 v1: Calls leverage of 0.81 moderate-to-high and says Director 4 holds an executive role; long profile layout
- SYN-000029 v3: Verdict reason oddly lists recent director appointments as a reason for low concern
- SYN-000546 v3: Says solid recovery but never shows the FY2022 and FY2023 losses behind it
- SYN-000546 v1: Verdict buried at the end of a long profile with hype words like robust
- SYN-001389 v1: Calls 1.03 the current ratio when it is the quick ratio (current 1.20); never counts the 3 winding-up petitions
- SYN-001389 v3: Winding-up line does not say which petition is still pending (RM 50.1k)
- SYN-000397 v3: Omits the settled RM 7.43m debt recovery case from the dispute history
- SYN-000397 v1: Files the two judgments under resolved cases and leads the concern with a settled case
- SYN-000545 v3: Verdict says active insolvency petitions but neither petition is pending
- SYN-000545 v1: Winding-up petitions and pending cases given without counts or claim totals
- SYN-000451 v3: Does not mention the dismissed RM 106.9k case against the company
- SYN-000451 v1: Long profile layout; debt service coverage of -0.81x not stated
- SYN-000785 v1: Claims operating expenses exceeded revenue in 2024 (RM 11.65m vs RM 13.38m); omits debt service strain
- SYN-000785 v3: Calls 2023 director appointments recent though they are outside the last 12 months
- SYN-000217 v3: No material problem found; every number and flag checks out
- SYN-000217 v1: Leans positive on a High concern company and omits the 2.65x leverage flag
- SYN-001203 v3: Does not label Gemilang Holdings as the corporate parent; bracket tag adds clutter
- SYN-001203 v1: Says yes worth a look with unsupported praise despite no financial statements
- SYN-001298 v3: Does not say the company is under 3 years old
- SYN-001298 v1: Omits debt service strain and the one-year-only gap; tone leans positive
