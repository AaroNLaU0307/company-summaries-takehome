"""Build the blinded manual review sheet for the ten pre-picked companies.

    uv run python -m evaluation.manual_sheet v1 v2           # refuses to overwrite a sheet that has scores in it

Writes docs/manual_review_sheet.md (to read), docs/manual_review_sheet.csv (to score) and docs/manual_review_key.csv
(which label is which version; do not open it before scoring).
"""

import csv
import random
import sys

from evaluation.run import SUMMARIES, load_summaries
from summarizer.data import ROOT, companies_by_id

DOCS = ROOT / "docs"
SAMPLE = [
    "SYN-000029",
    "SYN-000546",
    "SYN-001389",
    "SYN-000397",
    "SYN-000545",
    "SYN-000451",
    "SYN-000785",
    "SYN-000217",
    "SYN-001203",
    "SYN-001298",
]
SCORE_COLUMNS = ["faithful_0_2", "red_flags_0_2", "verdict_0_2", "readable_0_2", "biggest_problem"]
SEED = 7


def _has_scores(path) -> bool:
    if not path.is_file():
        return False
    with path.open(encoding="utf-8", newline="") as f:
        return any(any((row.get(c) or "").strip() for c in SCORE_COLUMNS) for row in csv.DictReader(f))


def main() -> None:
    versions = sys.argv[1:] or ["v1", "v2"]
    sheet_csv = DOCS / "manual_review_sheet.csv"
    if _has_scores(sheet_csv) and "--force" not in versions:
        sys.exit("docs/manual_review_sheet.csv already has scores; not overwriting.")
    versions = [v for v in versions if v != "--force"]
    companies = companies_by_id()
    summaries = {v: load_summaries(SUMMARIES / f"{v}.jsonl") if (SUMMARIES / f"{v}.jsonl").is_file() else {} for v in versions}
    rng = random.Random(SEED)
    labels = "ABCDEFG"
    md = [
        "# Manual review sheet (blinded)",
        "",
        "Read each summary, check it against the record, then score it in `manual_review_sheet.csv`. Rubric: "
        "`docs/definition_of_good.md`. Do not open `manual_review_key.csv` until you have finished.",
        "",
    ]
    sheet_rows, key_rows = [], []
    for reg in SAMPLE:
        c = companies[reg]
        order = versions[:]
        rng.shuffle(order)
        md += [f"## {reg}: {c['profile']['companyName']}", ""]
        for label, v in zip(labels, order, strict=False):
            text = summaries[v].get(reg, "(no summary yet: generate the summaries, then rebuild this sheet)")
            quoted = "\n".join("> " + line if line.strip() else ">" for line in text.splitlines())
            md += [f"### Summary {label}", "", quoted, ""]
            sheet_rows.append({"registrationNumber": reg, "label": label, **dict.fromkeys(SCORE_COLUMNS, "")})
            key_rows.append({"registrationNumber": reg, "label": label, "version": v})
    (DOCS / "manual_review_sheet.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with sheet_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["registrationNumber", "label", *SCORE_COLUMNS])
        w.writeheader()
        w.writerows(sheet_rows)
    with (DOCS / "manual_review_key.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["registrationNumber", "label", "version"])
        w.writeheader()
        w.writerows(key_rows)
    print(f"wrote manual review sheet for {len(SAMPLE)} companies x {len(versions)} versions")


if __name__ == "__main__":
    main()
