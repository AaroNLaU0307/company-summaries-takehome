"""Load the company records."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = ROOT / "data" / "companies.jsonl"
RECORD_DATE = "2025-12-31"


def load_companies(path: Path = COMPANIES) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def companies_by_id(path: Path = COMPANIES) -> dict[str, dict]:
    return {c["registrationNumber"]: c for c in load_companies(path)}
