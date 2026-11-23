"""Score every summaries/<version>.jsonl against the record and the facts sheet. Offline: never calls a model.

    uv run python -m evaluation.run                  # all versions in summaries/
    uv run python -m evaluation.run v1 v2

Writes results/eval_report.md (cited by CASE_STUDY.md) and results/eval_details.json.
Hand-check files in results/ (made by `python -m evaluation.handcheck`) are folded into the report when filled in.
"""

import csv
import json
import statistics
import sys
from pathlib import Path

from evaluation.checks import contradictions, financials_labelled, flag_results, stated_verdict, structure_ok, word_count
from evaluation.numbers import check_summary
from summarizer.data import ROOT, load_companies
from summarizer.facts import build_facts
from summarizer.prompts import STRUCTURED_VERSIONS

SUMMARIES = ROOT / "summaries"
RESULTS = ROOT / "results"
MATERIAL_KINDS = ("money", "percent", "ratio")
LENGTH_MIN, LENGTH_MAX = 80, 150


def load_summaries(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["registrationNumber"]] = row["summary"]
    return out


def score_version(version: str, summaries: dict[str, str], companies: list[dict]) -> dict:
    by_id = {c["registrationNumber"]: c for c in companies}
    order = [c["registrationNumber"] for c in companies]
    per_company = []
    for reg, text in summaries.items():
        company = by_id[reg]
        fs = build_facts(company)
        control = by_id[order[(order.index(reg) + 1) % len(order)]]
        nums = check_summary(text, company)
        ctrl = check_summary(text, control)
        flags = flag_results(text, fs)
        ok, missing = structure_ok(text)
        per_company.append(
            {
                "registrationNumber": reg,
                "triage": fs.triage,
                "words": word_count(text),
                "structure_ok": ok,
                "structure_missing": missing,
                "stated_verdict": stated_verdict(text),
                "financials_labelled": financials_labelled(text) if company["financials"]["years"] and version in STRUCTURED_VERSIONS else None,
                "numbers": [
                    {"text": m.num.text, "kind": m.num.kind, "matched": m.matched, "path": m.path, "context": m.context}
                    for m in nums
                ],
                "control_company": control["registrationNumber"],
                "control_numbers": [{"text": m.num.text, "kind": m.num.kind, "matched": m.matched} for m in ctrl],
                "flags": [{"id": f.flag_id, "severity": f.severity, "hit": f.hit} for f in flags],
                "contradictions": contradictions(text, fs, company),
            }
        )
    return {"version": version, "companies": per_company, "metrics": metrics(version, per_company)}


def _share(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def metrics(version: str, rows: list[dict]) -> dict:
    nums = [n for r in rows for n in r["numbers"]]
    mat = [n for n in nums if n["kind"] in MATERIAL_KINDS]
    ctrl = [n for r in rows for n in r["control_numbers"] if n["kind"] in MATERIAL_KINDS]
    flags = [f for r in rows for f in r["flags"]]
    high = [f for f in flags if f["severity"] == "high"]
    material = [f for f in flags if f["severity"] in ("high", "medium")]
    low = [f for f in flags if f["severity"] == "low"]
    words = [r["words"] for r in rows]
    with_verdict = [r for r in rows if r["stated_verdict"]]
    return {
        "summaries": len(rows),
        "numbers_all": len(nums),
        "numbers_material": len(mat),
        "untraceable_material": sum(not n["matched"] for n in mat),
        "untraceable_material_share": _share(sum(not n["matched"] for n in mat), len(mat)),
        "untraceable_all_share": _share(sum(not n["matched"] for n in nums), len(nums)),
        "summaries_with_untraceable": sum(any(not n["matched"] and n["kind"] in MATERIAL_KINDS for n in r["numbers"]) for r in rows),
        "control_traceable_material_share": _share(sum(n["matched"] for n in ctrl), len(ctrl)),
        "recall_material": _share(sum(f["hit"] is not None for f in material), len(material)),
        "recall_material_counts": f"{sum(f['hit'] is not None for f in material)}/{len(material)}",
        "recall_high": _share(sum(f["hit"] is not None for f in high), len(high)),
        "recall_high_counts": f"{sum(f['hit'] is not None for f in high)}/{len(high)}",
        "recall_low": _share(sum(f["hit"] is not None for f in low), len(low)),
        "summaries_all_material_flags": sum(
            all(f["hit"] is not None for f in r["flags"] if f["severity"] in ("high", "medium")) for r in rows
        ),
        "contradictions": sum(len(r["contradictions"]) for r in rows),
        "words_median": statistics.median(words) if words else None,
        "words_min": min(words) if words else None,
        "words_max": max(words) if words else None,
        "length_compliance": _share(sum(LENGTH_MIN <= w <= LENGTH_MAX for w in words), len(words)),
        "structure_compliance": _share(sum(r["structure_ok"] for r in rows), len(rows)),
        "structure_requested": version in STRUCTURED_VERSIONS,
        "verdict_stated": len(with_verdict),
        "financials_labelled": _share(sum(r["financials_labelled"] is True for r in rows), sum(r["financials_labelled"] is not None for r in rows)),
        "financials_labelled_counts": f"{sum(r['financials_labelled'] is True for r in rows)}/{sum(r['financials_labelled'] is not None for r in rows)}",
        "verdict_agreement": _share(sum(r["stated_verdict"] == r["triage"].lower() for r in with_verdict), len(with_verdict)),
    }


def read_handcheck(name: str) -> list[dict]:
    path = RESULTS / name
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("agent_judgement", "").strip()]


def handcheck_metrics() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in read_handcheck("handcheck_untraceable.csv"):
        d = out.setdefault(r["version"], {})
        d.setdefault("untraceable", []).append(r["agent_judgement"].strip())
    for r in read_handcheck("handcheck_traced.csv"):
        d = out.setdefault(r["version"], {})
        d.setdefault("traced", []).append(r["agent_judgement"].strip())
    for r in read_handcheck("handcheck_flags.csv"):
        d = out.setdefault(r["version"], {})
        d.setdefault(f"flag_{r['sample']}", []).append(r["agent_judgement"].strip())
    return out


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float) and v <= 1.0:
        return f"{v * 100:.1f}%"
    return str(v)


def write_report(results: list[dict]) -> str:
    hc = handcheck_metrics()
    n = results[0]["metrics"]["summaries"] if results else 0
    lines = [
        "# Evaluation report",
        "",
        "Generated by `uv run python -m evaluation.run`. Offline; reads summaries/ and data/ only.",
        f"All versions are scored on the same {n} companies (those present in every version).",
        "",
    ]
    rows = [
        ("Summaries scored", "summaries"),
        ("Numbers checked (money, percent, ratio)", "numbers_material"),
        ("Untraceable numbers (share)", "untraceable_material_share"),
        ("Untraceable numbers (count)", "untraceable_material"),
        ("Summaries with at least one untraceable number", "summaries_with_untraceable"),
        ("Negative control: share traceable against a different company", "control_traceable_material_share"),
        ("Red-flag recall, high + medium", "recall_material"),
        ("Red-flag recall, high + medium (hits/flags)", "recall_material_counts"),
        ("Red-flag recall, high only", "recall_high"),
        ("Red-flag recall, high only (hits/flags)", "recall_high_counts"),
        ("Red-flag recall, low (context)", "recall_low"),
        ("Summaries mentioning every material flag", "summaries_all_material_flags"),
        ("Contradiction hits", "contradictions"),
        ("Words, median", "words_median"),
        ("Words, min to max", None),
        ("Length within 80 to 150 words", "length_compliance"),
        ("Fixed structure present (asked for only in v2)", "structure_compliance"),
        ("Financials line labels its numbers (structured versions, added after reading v2)", "financials_labelled_counts"),
        ("Summaries stating a triage verdict", "verdict_stated"),
        ("Verdict matches computed triage (of those stating one)", "verdict_agreement"),
    ]
    head = "| Metric | " + " | ".join(r["version"] for r in results) + " |"
    lines += ["## Headline metrics", "", head, "|---|" + "---|" * len(results)]
    for label, key in rows:
        if key is None:
            vals = [f"{r['metrics']['words_min']} to {r['metrics']['words_max']}" for r in results]
        else:
            vals = [_fmt(r["metrics"][key]) if not key.endswith("counts") else r["metrics"][key] for r in results]
            if key in ("summaries", "numbers_material", "untraceable_material", "summaries_with_untraceable", "contradictions", "verdict_stated", "summaries_all_material_flags", "words_median"):
                vals = [str(r["metrics"][key]) for r in results]
        lines.append(f"| {label} | " + " | ".join(vals) + " |")

    lines += ["", "## Hand checks (done by the Claude Code agent, not by Aaron)", ""]
    if not hc:
        lines.append("Not filled in yet. Run `uv run python -m evaluation.handcheck` and fill the `agent_judgement` column.")
    for version, d in sorted(hc.items()):
        u = d.get("untraceable", [])
        t = d.get("traced", [])
        fa = sum(x == "false_alarm" for x in u)
        lines.append(f"- **{version}**: untraceable sample {len(u)}: {sum(x == 'hallucination' for x in u)} real errors, "
                     f"{fa} checker false alarms, {sum(x == 'unclear' for x in u)} unclear. "
                     f"False-alarm rate {_fmt(_share(fa, len(u)))}.")
        if t:
            co = sum(x == "coincidental" for x in t)
            lines.append(f"  Traced sample {len(t)}: {co} matched by coincidence to the wrong field ({_fmt(_share(co, len(t)))}).")
        for kind in ("hit", "miss"):
            j = d.get(f"flag_{kind}", [])
            if j:
                good = sum(x in ("correct", "true_miss") for x in j)
                lines.append(f"  Flag {kind}es sample {len(j)}: {good} confirmed, {len(j) - good} pattern errors.")

    for r in results:
        v = r["version"]
        lines += ["", f"## {v}: red-flag misses (high and medium)", ""]
        misses = [(c["registrationNumber"], f["id"]) for c in r["companies"] for f in c["flags"] if f["severity"] in ("high", "medium") and f["hit"] is None]
        by_flag: dict[str, list[str]] = {}
        for reg, fid in misses:
            by_flag.setdefault(fid, []).append(reg)
        if not by_flag:
            lines.append("None.")
        for fid, regs in sorted(by_flag.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"- `{fid}` missed in {len(regs)}: {', '.join(regs)}")
        lines += ["", f"## {v}: untraceable numbers", ""]
        un = [(c["registrationNumber"], n) for c in r["companies"] for n in c["numbers"] if not n["matched"] and n["kind"] in MATERIAL_KINDS]
        if not un:
            lines.append("None.")
        for reg, n in un[:60]:
            lines.append(f"- {reg} `{n['text']}` ({n['kind']}): {n['context']}")
        if len(un) > 60:
            lines.append(f"- ... and {len(un) - 60} more (see results/eval_details.json)")
        con = [(c["registrationNumber"], x) for c in r["companies"] for x in c["contradictions"]]
        lines += ["", f"## {v}: contradiction hits", ""]
        lines += [f"- {reg}: {x}" for reg, x in con] or ["None."]
    text = "\n".join(lines) + "\n"
    return text


def main() -> None:
    companies = load_companies()
    versions = sys.argv[1:] or sorted(p.stem for p in SUMMARIES.glob("*.jsonl"))
    loaded = {v: load_summaries(SUMMARIES / f"{v}.jsonl") for v in versions}
    # Score every version on the same companies: those present in all versions.
    common = set.intersection(*(set(s) for s in loaded.values())) if loaded else set()
    results = []
    for v in versions:
        summaries = {k: t for k, t in loaded[v].items() if k in common}
        results.append(score_version(v, summaries, companies))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "eval_details.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    report = write_report(results)
    (RESULTS / "eval_report.md").write_text(report, encoding="utf-8")
    print(report.split("## Hand checks")[0])


if __name__ == "__main__":
    main()
