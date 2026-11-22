"""House style: no em dash character in any file we write (including model output after normalisation)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "runs", "__pycache__", ".pytest_cache", ".ruff_cache"}
SUFFIXES = {".py", ".md", ".jsonl", ".csv", ".json", ".toml", ".txt"}


def test_no_em_dash():
    offenders = []
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in SUFFIXES and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS):
            if chr(0x2014) in p.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(p.relative_to(ROOT)))
    assert offenders == []
