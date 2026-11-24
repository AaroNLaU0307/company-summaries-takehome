"""Unblind the filled manual review sheet and average the scores per version.

    uv run python -m evaluation.manual_score --reviewer "who scored the sheet"

Writes results/manual_review_results.md.
"""

import csv
import statistics
import sys

from evaluation.manual_sheet import DOCS, SCORE_COLUMNS
from summarizer.data import ROOT


def main() -> None:
    reviewer = "unspecified"
    if "--reviewer" in sys.argv:
        reviewer = sys.argv[sys.argv.index("--reviewer") + 1]
    with (DOCS / "manual_review_key.csv").open(encoding="utf-8", newline="") as f:
        key = {(r["registrationNumber"], r["label"]): r["version"] for r in csv.DictReader(f)}
    with (DOCS / "manual_review_sheet.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    numeric = [c for c in SCORE_COLUMNS if c.endswith("_0_2")]
    scored = [r for r in rows if all((r.get(c) or "").strip() for c in numeric)]
    if not scored:
        sys.exit("No scored rows yet.")
    by_version: dict[str, list[dict]] = {}
    for r in scored:
        by_version.setdefault(key[(r["registrationNumber"], r["label"])], []).append(r)
    lines = ["# Manual review results", "", f"Scored rows: {len(scored)} of {len(rows)}. Reviewer: {reviewer}.", ""]
    lines += ["| Version | n | " + " | ".join(numeric) + " | total (of 8) |", "|---|---|" + "---|" * (len(numeric) + 1)]
    for v, rs in sorted(by_version.items()):
        means = [statistics.mean(float(r[c]) for r in rs) for c in numeric]
        lines.append(f"| {v} | {len(rs)} | " + " | ".join(f"{m:.2f}" for m in means) + f" | {sum(means):.2f} |")
    lines += ["", "## Notes", ""]
    for r in scored:
        if r.get("biggest_problem", "").strip():
            lines.append(f"- {r['registrationNumber']} {key[(r['registrationNumber'], r['label'])]}: {r['biggest_problem'].strip()}")
    out = ROOT / "results" / "manual_review_results.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
