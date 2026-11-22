# Manual review plan (picked before any summary was generated)

Who: Aaron. The agent that built the system must not fill this in, and nothing here is labelled "manual" unless a
person did it. Time: about 30 to 40 minutes.

## The ten companies

Picked from the facts sheet to cover each kind of company the team will see, before any model was called:

| Company | Why it is in the sample | Computed triage |
|---|---|---|
| SYN-000029 | Clean: no material flags, two directors appointed in 2025 | Low concern |
| SYN-000546 | Clean and large (revenue RM 266m) | Low concern |
| SYN-001389 | Heavy litigation: 8 defendant cases, 3 of them winding-up petitions | High concern |
| SYN-000397 | Litigation with judgments entered, missing FY2023 | High concern |
| SYN-000545 | Status "Winding up" but profitable; going-concern opinion in FY2022 | High concern |
| SYN-000451 | Negative equity, losses, recent name change | High concern |
| SYN-000785 | Losses, liabilities 24x equity, revenue down | Review |
| SYN-000217 | Disclaimer of audit opinion in FY2023 (not the latest year) | High concern |
| SYN-001203 | No financial statements at all; corporate parent | Review |
| SYN-001298 | Young company, one year of data, loss-making | Review |

## How to review

1. Open `docs/manual_review_sheet.md` and read each company's summaries. They are labelled A and B in a random order
   per company, so you do not know which version wrote which. Do not open `docs/manual_review_key.csv` until you
   are done.
2. Check each summary against the record (in the viewer, or `uv run python -m summarizer.facts SYN-xxxxxx`).
3. Fill in the score columns in `docs/manual_review_sheet.csv` with 0, 1 or 2 per criterion (rubric in
   `docs/definition_of_good.md`) and one note: the biggest problem with that summary.
4. Run `uv run python -m evaluation.manual_score` to unblind and write `results/manual_review_results.md`.
