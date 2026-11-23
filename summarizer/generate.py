"""Generate summaries and write summaries/<version>.jsonl.

    uv run python -m summarizer.generate                    # all versions, paired: v1 then v2 per company
    uv run python -m summarizer.generate --offline          # rebuild the jsonl files from the cache only (no calls)
    uv run python -m summarizer.generate --dry-run          # prompt sizes, no calls
    uv run python -m summarizer.generate --versions v2 --ids SYN-000029

Order: the ten manual-review companies first, then the rest in file order, each company through every version before
the next company. So if the free-tier daily cap stops the run, what exists is a complete paired sample with a rule
that can be stated. A daily-quota 429 stops the run at once; the files are then written from the cache.

Raw responses stay untouched in runs/. The only change between the raw response and the summary line is `normalise`.
"""

import argparse
import json
import re
import sys

from summarizer.data import ROOT, load_companies
from summarizer.llm import CachedClient, LLMError, QuotaExhausted, build_body, cache_path, extract_content, load_config, read_cached
from summarizer.prompts import VERSIONS

SUMMARIES = ROOT / "summaries"
# Pinned so that offline rebuilds and scoring always use the same request hashes as the run.
MODEL = "gemini-3.5-flash-lite"
TEMPERATURE = 0.0
MAX_TOKENS = 4096
REASONING_EFFORT = None
EM_DASH = chr(0x2014)
REVIEW_FIRST = [
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


def normalise(text: str) -> str:
    """The only post-processing step: strip a wrapping code fence, replace em dashes (house style), trim whitespace."""
    t = text.strip()
    fence = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", t, flags=re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    t = re.sub(r"\s*" + EM_DASH + r"\s*", ", ", t)
    return t


def body_for(version: str, company: dict, model: str = MODEL) -> dict:
    return build_body(model, VERSIONS[version](company), TEMPERATURE, MAX_TOKENS, REASONING_EFFORT)


def run_order(companies: list[dict]) -> list[dict]:
    by_id = {c["registrationNumber"]: c for c in companies}
    first = [by_id[r] for r in REVIEW_FIRST if r in by_id]
    return first + [c for c in companies if c["registrationNumber"] not in set(REVIEW_FIRST)]


def write_from_cache(versions: list[str], model: str = MODEL) -> dict[str, int]:
    companies = load_companies()
    SUMMARIES.mkdir(exist_ok=True)
    counts = {}
    for v in versions:
        lines = []
        for c in companies:
            cached = read_cached(cache_path(v, c["registrationNumber"], body_for(v, c, model)))
            if cached:
                lines.append(json.dumps({"registrationNumber": c["registrationNumber"], "summary": normalise(extract_content(cached))}, ensure_ascii=False))
        (SUMMARIES / f"{v}.jsonl").write_text("".join(x + "\n" for x in lines), encoding="utf-8", newline="\n")
        counts[v] = len(lines)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", nargs="*", default=sorted(VERSIONS))
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    companies = run_order(load_companies())
    if args.ids:
        companies = [c for c in companies if c["registrationNumber"] in set(args.ids)]

    if args.dry_run:
        for v in args.versions:
            chars = sum(len(m["content"]) for c in companies for m in VERSIONS[v](c))
            print(f"{v}: {len(companies)} prompts, about {chars // 4} input tokens (chars / 4)")
        return

    if not args.offline:
        client = CachedClient(load_config())
        stopped = None
        for i, c in enumerate(companies, 1):
            reg = c["registrationNumber"]
            for v in args.versions:
                try:
                    client.chat(v, reg, body_for(v, c))
                    print(f"[{i}/{len(companies)}] {reg} {v} ok", flush=True)
                except QuotaExhausted as e:
                    stopped = str(e)
                    break
                except LLMError as e:
                    print(f"[{i}/{len(companies)}] {reg} {v} FAILED: {e}", file=sys.stderr, flush=True)
            if stopped:
                print(f"STOPPED at {reg}: {stopped}", file=sys.stderr, flush=True)
                break
        print(f"API calls {client.calls_made}, cache hits {client.cache_hits}", flush=True)

    counts = write_from_cache(args.versions)
    print("wrote " + ", ".join(f"summaries/{v}.jsonl: {n} lines" for v, n in counts.items()))


if __name__ == "__main__":
    main()
