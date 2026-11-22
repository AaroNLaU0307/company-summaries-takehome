"""Draw fixed random samples for hand checking, after `evaluation.run` has written results/eval_details.json.

    uv run python -m evaluation.handcheck            # writes CSVs only if they do not exist yet (keeps judgements)
    uv run python -m evaluation.handcheck --force    # redraw (erases judgements)

Files (fill the agent_judgement column, then re-run evaluation.run):
- results/handcheck_untraceable.csv: numbers the checker could not trace. hallucination | false_alarm | unclear
- results/handcheck_traced.csv: numbers the checker did trace, with the field it matched. correct | coincidental
- results/handcheck_flags.csv: red-flag pattern hits and misses. hit: correct | false_hit; miss: true_miss | missed_by_pattern
"""

import csv
import json
import random
import sys

from summarizer.data import ROOT

RESULTS = ROOT / "results"
SEED = 20251231
N_UNTRACEABLE, N_TRACED, N_FLAGS = 25, 15, 12


def _write(name: str, rows: list[dict], force: bool) -> None:
    path = RESULTS / name
    if path.exists() and not force:
        print(f"keep existing {name}")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[*rows[0].keys(), "agent_judgement", "notes"] if rows else ["version"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "agent_judgement": "", "notes": ""})
    print(f"wrote {name}: {len(rows)} rows")


def main() -> None:
    force = "--force" in sys.argv
    results = json.loads((RESULTS / "eval_details.json").read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    untr, traced, flags = [], [], []
    for r in results:
        v = r["version"]
        un = [(c["registrationNumber"], n) for c in r["companies"] for n in c["numbers"] if not n["matched"] and n["kind"] != "count"]
        tr = [(c["registrationNumber"], n) for c in r["companies"] for n in c["numbers"] if n["matched"] and n["kind"] != "count"]
        hits = [(c["registrationNumber"], f) for c in r["companies"] for f in c["flags"] if f["severity"] != "low" and f["hit"]]
        miss = [(c["registrationNumber"], f) for c in r["companies"] for f in c["flags"] if f["severity"] != "low" and not f["hit"]]
        for reg, n in rng.sample(un, min(N_UNTRACEABLE, len(un))):
            untr.append({"version": v, "registrationNumber": reg, "number": n["text"], "kind": n["kind"], "context": n["context"]})
        for reg, n in rng.sample(tr, min(N_TRACED, len(tr))):
            traced.append({"version": v, "registrationNumber": reg, "number": n["text"], "matched_field": n["path"], "context": n["context"]})
        for sample, pool in (("hit", hits), ("miss", miss)):
            for reg, f in rng.sample(pool, min(N_FLAGS, len(pool))):
                flags.append({"version": v, "sample": sample, "registrationNumber": reg, "flag": f["id"], "snippet": f["hit"] or ""})
    _write("handcheck_untraceable.csv", untr, force)
    _write("handcheck_traced.csv", traced, force)
    _write("handcheck_flags.csv", flags, force)


if __name__ == "__main__":
    main()
