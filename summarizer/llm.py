"""OpenAI-compatible chat-completions client with a disk cache.

- Config comes from a small env file outside the repo (default `../secrets/llm.env`, override with `LLM_ENV_FILE`), or
  from environment variables of the same names: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, optional LLM_REASONING_EFFORT.
- The key is never printed, logged or written to the cache. Only the request body and the response body are cached.
- Every response is cached under runs/<version>/<registrationNumber>__<request hash>.json. A cached request is never sent
  again, so scoring and rebuilding the summaries files work offline.
- Empty content or finish_reason == "length" is treated as a failure and is not cached as a success.

`uv run python -m summarizer.llm --list-models` lists the models the key can use.
"""

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from summarizer.data import ROOT

RUNS = ROOT / "runs"
DEFAULT_ENV_FILE = ROOT.parent / "secrets" / "llm.env"

# Only used when the env file gives a key but no base URL, and the key prefix makes the provider obvious.
KEY_PREFIX_BASE_URLS = {
    "AIza": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "gsk_": "https://api.groq.com/openai/v1/",
    "sk-or-": "https://openrouter.ai/api/v1/",
}


class LLMError(RuntimeError):
    pass


class QuotaExhausted(LLMError):
    pass


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str | None
    reasoning_effort: str | None = None
    min_interval_s: float = 6.5


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def load_config() -> LLMConfig:
    path = Path(os.environ.get("LLM_ENV_FILE", DEFAULT_ENV_FILE))
    values = _read_env_file(path)
    get = lambda k: os.environ.get(k) or values.get(k)  # noqa: E731
    key = get("LLM_API_KEY")
    if not key:
        raise LLMError(f"No LLM_API_KEY found (looked in the environment and in {path.name}).")
    base = get("LLM_BASE_URL")
    if not base:
        base = next((u for prefix, u in KEY_PREFIX_BASE_URLS.items() if key.startswith(prefix)), None)
        if not base:
            raise LLMError("No LLM_BASE_URL given and the provider is not obvious from the key. Add LLM_BASE_URL.")
    interval = float(get("LLM_MIN_INTERVAL_S") or 6.5)
    return LLMConfig(key, base.rstrip("/") + "/", get("LLM_MODEL"), get("LLM_REASONING_EFFORT"), interval)


def list_models(cfg: LLMConfig) -> list[str]:
    r = httpx.get(cfg.base_url + "models", headers={"Authorization": f"Bearer {cfg.api_key}"}, timeout=30)
    if r.status_code != 200:
        raise LLMError(f"Listing models failed with HTTP {r.status_code}.")
    return sorted(m["id"] for m in r.json().get("data", []))


def request_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def cache_path(version: str, item_id: str, body: dict) -> Path:
    return RUNS / version / f"{item_id}__{request_hash(body)}.json"


def build_body(cfg_model: str, messages: list[dict], temperature: float, max_tokens: int, reasoning_effort: str | None) -> dict:
    body: dict = {"model": cfg_model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    return body


def read_cached(path: Path) -> dict | None:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def extract_content(entry: dict) -> str:
    return entry["response"]["choices"][0]["message"]["content"]


class CachedClient:
    def __init__(self, cfg: LLMConfig | None, offline: bool = False) -> None:
        self.cfg = cfg
        self.offline = offline
        self._last_call = 0.0
        self.calls_made = 0
        self.cache_hits = 0

    def chat(self, version: str, item_id: str, body: dict, max_attempts: int = 6) -> dict:
        path = cache_path(version, item_id, body)
        cached = read_cached(path)
        if cached is not None:
            self.cache_hits += 1
            return cached
        if self.offline or self.cfg is None:
            raise LLMError(f"Not cached and offline: {path.relative_to(ROOT)}")
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}
        delay = 10.0
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            wait = self.cfg.min_interval_s - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            t0 = time.monotonic()
            try:
                r = httpx.post(self.cfg.base_url + "chat/completions", headers=headers, json=body, timeout=120)
            except httpx.HTTPError as e:
                last_error = f"network error {type(e).__name__}"
                time.sleep(delay)
                delay *= 2
                continue
            elapsed = round(time.monotonic() - t0, 2)
            if r.status_code == 429 and "PerDay" in r.text:
                # A daily quota does not come back within minutes: stop the whole run instead of retrying.
                limit = re.search(r'"quotaValue":\s*"(\d+)"', r.text)
                quota_model = re.search(r'"model":\s*"([^"]+)"', r.text)
                raise QuotaExhausted(
                    f"daily quota reached (limit {limit.group(1) if limit else '?'} requests/day, "
                    f"metered as {quota_model.group(1) if quota_model else '?'})"
                )
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("retry-after")
                sleep_s = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else delay
                last_error = f"HTTP {r.status_code}: {r.text[:300]}"
                print(f"  {item_id}: {last_error[:120]}; retry {attempt}/{max_attempts} in {sleep_s:.0f}s", file=sys.stderr)
                time.sleep(sleep_s)
                delay = min(delay * 2, 120)
                continue
            if r.status_code != 200:
                raise LLMError(f"{item_id}: HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            if not content.strip() or choice.get("finish_reason") == "length":
                # Do not cache as a success. Keep a copy for diagnosis.
                bad = RUNS / version / "_failed" / f"{item_id}__{request_hash(body)}.json"
                bad.parent.mkdir(parents=True, exist_ok=True)
                bad.write_text(json.dumps({"request": body, "response": data}, indent=2, ensure_ascii=False), encoding="utf-8")
                raise LLMError(f"{item_id}: empty or truncated response (finish_reason={choice.get('finish_reason')})")
            entry = {
                "version": version,
                "item_id": item_id,
                "request_hash": request_hash(body),
                "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "elapsed_s": elapsed,
                "request": body,
                "response": data,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
            self.calls_made += 1
            return entry
        raise LLMError(f"{item_id}: gave up after {max_attempts} attempts ({last_error[:200]})")


def main() -> None:
    cfg = load_config()
    if "--list-models" in sys.argv:
        for m in list_models(cfg):
            print(m)
    else:
        print(f"base_url={cfg.base_url} model={cfg.model}")


if __name__ == "__main__":
    main()
