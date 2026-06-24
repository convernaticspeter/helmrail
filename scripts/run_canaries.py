#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from time import monotonic
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8765/v1"
DEFAULT_CANARIES = Path(__file__).resolve().parents[1] / "canaries" / "internal-pilot.jsonl"
DEFAULT_SECRET_FILE = Path.home() / ".hermes" / "secrets" / "helmrail-admin-api-key.txt"


def load_api_key() -> str:
    if os.getenv("HELMRAIL_API_KEY"):
        return os.environ["HELMRAIL_API_KEY"]
    if DEFAULT_SECRET_FILE.exists():
        return DEFAULT_SECRET_FILE.read_text().strip()
    return ""


def load_canaries(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"Line {line_no}: canary must be an object")
        if not item.get("id") or not item.get("prompt"):
            raise ValueError(f"Line {line_no}: canary requires id and prompt")
        item.setdefault("model", "helmrail-coordinator")
        items.append(item)
    return items


def call_chat(base_url: str, api_key: str, model: str, prompt: str) -> tuple[int, dict[str, Any], float, str]:
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base_url.rstrip('/')}/chat/completions", data=payload, headers=headers, method="POST")
    started = monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            body: dict[str, Any] = json.loads(response.read().decode())
            return response.status, body, monotonic() - started, response.headers.get("X-Helmrail-Trace-Id", "")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw)
            body = body if isinstance(body, dict) else {"error": body}
        except Exception:
            body = {"error": raw}
        return exc.code, body, monotonic() - started, exc.headers.get("X-Helmrail-Trace-Id", "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Helmrail internal pilot canaries.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--file", type=Path, default=DEFAULT_CANARIES)
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N canaries. 0 = all")
    parser.add_argument("--dry-run", action="store_true", help="Validate canary file without calling Helmrail")
    args = parser.parse_args(argv)

    canaries = load_canaries(args.file)
    if args.limit:
        canaries = canaries[: max(0, args.limit)]
    if args.dry_run:
        print(json.dumps({"ok": True, "loaded": len(canaries), "file": str(args.file)}, ensure_ascii=False))
        return 0

    api_key = load_api_key()
    failures = 0
    for item in canaries:
        status, body, elapsed, trace_id = call_chat(
            args.base_url,
            api_key,
            str(item.get("model") or "helmrail-coordinator"),
            str(item["prompt"]),
        )
        content = ""
        choices = body.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                raw_content = message.get("content")
                content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
        ok = 200 <= status < 300 and bool(content.strip())
        failures += 0 if ok else 1
        print(
            json.dumps(
                {
                    "id": item["id"],
                    "ok": ok,
                    "status": status,
                    "elapsed_ms": int(elapsed * 1000),
                    "trace_id": trace_id,
                    "chars": len(content),
                },
                ensure_ascii=False,
            )
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
