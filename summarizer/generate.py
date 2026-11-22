"""Generate summaries for one version and write summaries/<version>.jsonl.

    uv run python -m summarizer.generate v2                 # call the model for anything not cached
    uv run python -m summarizer.generate v2 --offline       # rebuild the jsonl from the cache only
    uv run python -m summarizer.generate v2 --dry-run       # print prompt sizes, no calls
    uv run python -m summarizer.generate v2 --ids SYN-000029 SYN-000545

Raw responses stay untouched in runs/. The only change between the raw response and the summary line is `normalise`
(documented below), so the summaries can always be rebuilt from the cache.
"""

import argparse
import json
import re
import sys

from summarizer.data import ROOT, load_companies
from summarizer.llm import CachedClient, LLMError, build_body, cache_path, extract_content, load_config, read_cached
from summarizer.prompts import VERSIONS

SUMMARIES = ROOT / "summaries"
TEMPERATURE = 0.0
MAX_TOKENS = 4096
EM_DASH = chr(0x2014)


def normalise(text: str) -> str:
    """The only post-processing step: strip a wrapping code fence, replace em dashes (house style), trim whitespace."""
    t = text.strip()
    fence = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", t, flags=re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    t = re.sub(r"\s*" + EM_DASH + r"\s*", ", ", t)
    return t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", choices=sorted(VERSIONS))
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", help="override the model from the env file")
    args = ap.parse_args()

    all_companies = load_companies()
    selected = set(args.ids) if args.ids else {c["registrationNumber"] for c in all_companies}
    companies = [c for c in all_companies if c["registrationNumber"] in selected]
    build = VERSIONS[args.version]

    if args.dry_run:
        total = 0
        for c in companies:
            chars = sum(len(m["content"]) for m in build(c))
            total += chars
        print(f"{args.version}: {len(companies)} prompts, about {total // 4} input tokens (chars / 4)")
        return

    cfg = None if args.offline else load_config()
    model = args.model or (cfg.model if cfg else None) or _model_from_cache(args.version)
    if not model:
        sys.exit("No model: set LLM_MODEL in the env file or pass --model.")
    client = CachedClient(cfg, offline=args.offline)
    effort = cfg.reasoning_effort if cfg else _effort_from_cache(args.version)

    out_path = SUMMARIES / f"{args.version}.jsonl"
    summaries: dict[str, str] = {}
    failures = []
    for i, c in enumerate(companies, 1):
        reg = c["registrationNumber"]
        body = build_body(model, build(c), TEMPERATURE, MAX_TOKENS, effort)
        try:
            entry = client.chat(args.version, reg, body)
        except LLMError as e:
            failures.append(str(e))
            print(f"[{i}/{len(companies)}] {reg} FAILED: {e}", file=sys.stderr)
            continue
        summaries[reg] = normalise(extract_content(entry))
        print(f"[{i}/{len(companies)}] {reg} ok")
    # Companies not selected this time: include them only if the cache holds a response to the same request.
    for c in all_companies:
        reg = c["registrationNumber"]
        if reg not in selected:
            cached = read_cached(cache_path(args.version, reg, build_body(model, build(c), TEMPERATURE, MAX_TOKENS, effort)))
            if cached:
                summaries[reg] = normalise(extract_content(cached))

    order = [c["registrationNumber"] for c in all_companies]
    SUMMARIES.mkdir(exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for reg in order:
            if reg in summaries:
                f.write(json.dumps({"registrationNumber": reg, "summary": summaries[reg]}, ensure_ascii=False) + "\n")
    print(f"wrote {out_path.relative_to(ROOT)}: {len(summaries)} lines; API calls {client.calls_made}, cache hits {client.cache_hits}")
    if failures:
        print(f"{len(failures)} failure(s)", file=sys.stderr)
        sys.exit(1)


def _cached_entries(version: str) -> list[dict]:
    d = ROOT / "runs" / version
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.is_dir() else []


def _model_from_cache(version: str) -> str | None:
    entries = _cached_entries(version)
    return entries[0]["request"]["model"] if entries else None


def _effort_from_cache(version: str) -> str | None:
    entries = _cached_entries(version)
    return entries[0]["request"].get("reasoning_effort") if entries else None


if __name__ == "__main__":
    main()
