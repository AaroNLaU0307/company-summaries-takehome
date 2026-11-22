# What a good summary is (written before any summary was generated)

Status: draft, pending Aaron's approval. This file was committed before any prompt, model call or summary existed, so
the git history shows the definition came first. Any later change to it, to the thresholds or to the keyword lists in
`evaluation/` is listed in the change log at the bottom and disclosed in `CASE_STUDY.md`.

## The reader and the decision

The reader is someone on a supplier-vetting team. They open a company page and must decide, in about 30 seconds,
whether this company is worth a closer look (or should be dropped, or needs a specific follow-up question). They will
read the full record afterwards if the company goes ahead. So the summary is a **triage note**, not a profile:

- It exists to surface reasons for concern quickly. A missed red flag costs more than a missed nice-to-know fact,
  because a missed red flag can mean signing a supplier that later fails or is in a dispute.
- It must be trustworthy enough to act on. If a reader catches one invented number, they stop trusting every summary,
  and the summaries become useless. So faithfulness comes before polish.
- It should look the same every time, so the reader learns where to look.

## The definition

A good summary is:

1. **Faithful.** Every number and fact in it can be found in, or computed directly from, the company's record. No
   invented figures, no outside knowledge, no guessed causes ("due to the pandemic").
2. **Complete on red flags.** It mentions every material red flag listed in the table below that applies to the
   company, with the key number (count, amount or ratio) where there is one.
3. **Honest about gaps.** When data is missing (no financial statements, only one year, a missing year), it says so
   ("no data", "only FY2024 filed") instead of describing a trend that cannot be seen.
4. **Short and fixed in shape.** About 80 to 150 words, in this order:
   - **Verdict:** one line, the triage level and the main reason.
   - **Key risks:** a short list of the red flags, most serious first (or "None found in the record").
   - **Financials:** latest year's revenue, profit after tax, equity and one liquidity figure, with the trend where
     there are at least two years.
   - **People and ownership:** number of directors, any appointments in the last 12 months, the main shareholder(s),
     any corporate parent.
   - **Data gaps:** what is missing, or "None".
5. **Plain.** Short sentences, amounts in RM with a clear unit (for example "RM 5.35m"), ratios written consistently.
   No hype or filler ("robust", "solid", "well-positioned").

What a summary is not for: it does not give a credit score or a final yes/no, and it does not repeat the full record.

## Dates

The records are as of **31 December 2025**. "Recent" is measured from that date, not from today:

- recent director appointment: appointed on or after 2025-01-01 (last 12 months);
- recent name change: changed on or after 2024-01-01 (last 24 months);
- young company: incorporated on or after 2023-01-01 (less than 3 years old).

## Red flags (computed in plain Python, in `summarizer/facts.py`)

These rules are the evaluation ground truth. They are my judgement of what a vetting team would want to see first;
the thresholds are conventional rules of thumb, not tuned to this data.

| Flag | Severity | Rule |
|---|---|---|
| `STATUS_NOT_ACTIVE` | high | Company status is anything other than "Active" (for example "Winding up"). Status outranks the financials: a winding-up company with a profit is still high concern. |
| `WINDING_UP_PETITION` | high | The company is the **defendant** in at least one winding-up petition, whatever its status. Counted separately from other cases. |
| `NON_CLEAN_AUDIT` | high | Any year's audit opinion is not plain "Unqualified" (disclaimer, adverse, qualified, or a material uncertainty on going concern). Every year is checked, and the summary must say which year. |
| `NEGATIVE_EQUITY` | high | Latest year total equity is below zero (liabilities exceed assets). When this applies, the leverage flag is suppressed, because the leverage ratio is meaningless with negative equity. |
| `DEFENDANT_JUDGMENT` | high | At least one case (other than winding-up petitions) where the company is the defendant and the status is "Judgment entered". |
| `DEFENDANT_PENDING` | medium | At least one pending case (other than winding-up petitions) where the company is the defendant. Count and total claim amount reported. |
| `NET_LOSS` | medium | Latest year profit after tax is below zero. |
| `REVENUE_DECLINE` | medium | Latest year revenue is at least 10% below the previous available year. If a year is missing in between, the change is labelled as a two-year change. |
| `NEGATIVE_OPERATING_CASH_FLOW` | medium | Latest year operating cash flow is below zero. |
| `WEAK_LIQUIDITY` | medium | Latest year quick ratio below 1.0. |
| `DEBT_SERVICE_STRAIN` | medium | Latest year interest coverage below 1.5 or debt service coverage below 1.0. |
| `HIGH_LEVERAGE` | medium | Latest year total liabilities to equity above 2.0, with positive equity. |
| `NO_FINANCIALS` | medium | No financial statements in the record. The company cannot be assessed financially. |
| `RECENT_DIRECTOR_APPOINTMENT` | low | At least one director appointed in the last 12 months. |
| `RECENT_NAME_CHANGE` | low | A former name changed in the last 24 months. |
| `YOUNG_COMPANY` | low | Incorporated less than 3 years before the record date. |
| `SHORT_HISTORY` | low | Only one year of financial statements, so no trend can be seen. |
| `MISSING_YEAR` | low | A gap between financial years (for example FY2022 and FY2024 but no FY2023). |
| `DEFENDANT_CASES_CLOSED` | low | Defendant cases that are settled, dismissed or withdrawn (history of disputes, not open exposure). |

Only cases where the company is the **defendant** count as risk. Cases it brings as plaintiff (mostly debt recovery)
are context, not red flags.

**Triage level** (also computed, and used as the expected verdict):

- **High concern**: any high flag.
- **Review**: no high flag, at least one medium flag.
- **Low concern**: no high or medium flags.

### What the record does not let us compute

- **Shareholder changes.** Shareholders have no dates, so "recent change of shareholder" cannot be detected.
- **Director departures.** Only current directors with an appointment date are listed. We can flag recent
  appointments, not resignations.
- **Anything after the latest financial year.** The latest statements are FY2024 for every company that has any. The
  summary should not describe 2025 performance.

## How each part of the definition is checked

| Part of the definition | Check | Type |
|---|---|---|
| Faithful (numbers) | Every number in the summary is extracted and matched against the record and the facts sheet, with tolerance for units (RM m / k), percent versus decimal, and rounding to the displayed precision. Reported as the share of numbers that cannot be traced. A negative control scores each summary against a different company's record, to show how often the checker accepts a number by coincidence. | automatic |
| Faithful (checker quality) | A sample of numbers the checker flags as untraceable is checked by hand to estimate its false-alarm rate. | hand check (agent), reported as such |
| Complete on red flags | For each high and medium flag that applies, the summary must mention it (keyword patterns per flag). Reported as recall per version, with the list of misses. Low flags reported separately. | automatic, with a hand-checked sample of hits and misses |
| No contradictions | Simple patterns that contradict the facts, for example "no litigation" when the company is a defendant, or "profitable" when the latest year is a loss. | automatic |
| Correct verdict | For versions that state a verdict, it must match the computed triage level. | automatic |
| Short and fixed in shape | Word count between 80 and 150; the five section labels present in order. | automatic |
| Useful and clear to the reader | Ten companies, picked in advance (see `docs/manual_review_plan.md`), scored by a person with the rubric below. | manual (Aaron) |

## Manual review rubric (0, 1 or 2 per criterion)

| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Faithful | At least one wrong number or fact | Vague or slightly misleading wording, no wrong facts | Everything checks out against the record |
| Red flags | Misses a high-severity flag | Misses a medium flag, or a flag is mentioned without its key number | All material flags present with key numbers |
| Verdict | Wrong triage call (would mislead the decision) | Right direction, wrong emphasis | Right call, right main reason |
| Readable in 30 seconds | Have to read the full record anyway | Usable but cluttered or out of order | Can decide from the summary alone |

Plus one free-text note per summary: "the biggest problem with this summary".

## Change log

- 2026-11-22, after a 2-company trial run (SYN-000451, SYN-000545) and before the full runs were scored: two bug
  fixes in the evaluation code, no change to the definition, the flags or the thresholds. (1) The number extractor
  now reads "MYR" as well as "RM", because v1 wrote amounts as "MYR 13.0M". (2) The flag keyword patterns used
  "[^.]" to stay inside one sentence, which stopped at the decimal point in "0.63", so "quick ratio 0.63 (below
  1.0)" was missed. Patterns now allow a full stop followed by a digit. "liquidity risk" was added to the
  weak-liquidity patterns.
