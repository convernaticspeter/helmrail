from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


HERMES_AGENT_DIR = Path.home() / ".hermes" / "hermes-agent"
HERMES_AGENT_PYTHON = HERMES_AGENT_DIR / "venv" / "bin" / "python"
PRO_ORACLE_MODULE = HERMES_AGENT_DIR / "hermes_cli" / "pro_oracle.py"
NODE24 = Path("/opt/homebrew/opt/node@24/bin/node")
ORACLE_CLI = Path.home() / ".hermes" / "vendor" / "oracle" / "dist" / "bin" / "oracle-cli.js"
ORACLE_PROFILE = Path.home() / ".oracle" / "browser-profile"


PROVIDER_PRESETS: list[dict[str, Any]] = [
    {
        "id": "openai_codex_cli",
        "label": "OpenAI Subscription / Codex CLI",
        "provider": "openai",
        "plan": "ChatGPT/Codex subscription",
        "connector_type": "codex_cli",
        "credential_ref": "codex",
        "base_url": "",
        "api_style": "codex_cli",
        "model_aliases": ["gpt-5.5", "gpt-5.4", "codex"],
        "requires_api_key": False,
        "key_policy": "forbidden",
        "help": "No OpenAI key entry. Link the paid OpenAI subscription through the local Codex CLI/OAuth login.",
    },
    {
        "id": "chatgpt_oracle",
        "label": "GPT-5.5 Pro / Oracle browser",
        "provider": "chatgpt",
        "plan": "ChatGPT Pro via Oracle",
        "connector_type": "oracle_browser",
        "credential_ref": str(ORACLE_PROFILE),
        "base_url": "",
        "api_style": "oracle_browser",
        "model_aliases": ["gpt-5.5-pro"],
        "requires_api_key": False,
        "key_policy": "forbidden",
        "help": "Uses Hermes /pro Oracle browser automation to ask GPT-5.5 Pro through the logged-in ChatGPT Pro browser profile.",
    },
    {
        "id": "zai_coding",
        "label": "Z.ai Coding Plan",
        "provider": "zai",
        "plan": "Z.ai Coding Plan",
        "connector_type": "api_key_local",
        "credential_ref": "",
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "api_style": "openai_compatible",
        "model_aliases": ["glm-5.2", "glm-5-turbo"],
        "requires_api_key": True,
        "key_policy": "api_key_allowed",
        "help": "Z.ai coding-plan endpoint. Uses API key auth and an OpenAI-compatible chat/completions route.",
    },
    {
        "id": "kimi_coding",
        "label": "Kimi Coding Plan",
        "provider": "kimi",
        "plan": "Kimi K2.7 Code",
        "connector_type": "api_key_local",
        "credential_ref": "",
        "base_url": "https://api.moonshot.ai/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["kimi-k2.7-code", "kimi-k2.7-code-highspeed"],
        "requires_api_key": True,
        "key_policy": "api_key_allowed",
        "help": "Kimi/Moonshot OpenAI-compatible API. Coding model IDs are prefilled.",
    },
    {
        "id": "minimax_coding",
        "label": "MiniMax Coding Plan",
        "provider": "minimax",
        "plan": "MiniMax-M3",
        "connector_type": "api_key_local",
        "credential_ref": "",
        "base_url": "https://api.minimaxi.com/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["MiniMax-M3"],
        "requires_api_key": True,
        "key_policy": "api_key_allowed",
        "help": "MiniMax OpenAI-compatible API. MiniMax-M3 is the coding/agentic preset.",
    },
    {
        "id": "anthropic_api",
        "label": "Anthropic API",
        "provider": "anthropic",
        "plan": "Claude API",
        "connector_type": "api_key_local",
        "credential_ref": "",
        "base_url": "https://api.anthropic.com",
        "api_style": "anthropic_native",
        "model_aliases": ["claude-sonnet-4.6", "claude-opus-4.8"],
        "requires_api_key": True,
        "key_policy": "api_key_allowed",
        "help": "API product only. Do not bridge a consumer Claude subscription; use an Anthropic API key.",
    },
    {
        "id": "google_gemini_api",
        "label": "Google Gemini API",
        "provider": "google",
        "plan": "Gemini API",
        "connector_type": "api_key_local",
        "credential_ref": "",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_style": "gemini_native",
        "model_aliases": ["gemini-3.5-pro", "gemini-3.5-flash"],
        "requires_api_key": True,
        "key_policy": "api_key_allowed",
        "help": "API product only. Do not bridge a consumer Google/Gemini subscription; use a Gemini API key.",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "provider": "openrouter",
        "plan": "OpenRouter API",
        "connector_type": "api_key_local",
        "credential_ref": "",
        "base_url": "https://openrouter.ai/api/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["openrouter/auto"],
        "requires_api_key": True,
        "key_policy": "api_key_allowed",
        "help": "OpenAI-compatible router. Enter any model enabled in OpenRouter.",
    },
    {
        "id": "custom_openai",
        "label": "Custom OpenAI-compatible API",
        "provider": "custom",
        "plan": "Custom API",
        "connector_type": "api_key_local",
        "credential_ref": "",
        "base_url": "",
        "api_style": "openai_compatible",
        "model_aliases": [],
        "requires_api_key": True,
        "key_policy": "api_key_allowed",
        "help": "Use for another OpenAI-compatible API. Not for OpenAI subscription access.",
    },
]


PRESETS_BY_PROVIDER = {preset["provider"]: preset for preset in PROVIDER_PRESETS}


def public_presets() -> list[dict[str, Any]]:
    return PROVIDER_PRESETS


def api_style_for(subscription: dict[str, Any]) -> str:
    metadata = subscription.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("api_style"):
        return str(metadata["api_style"])
    provider = str(subscription.get("provider") or "")
    return str(PRESETS_BY_PROVIDER.get(provider, {}).get("api_style") or "openai_compatible")


def resolve_secret(subscription: dict[str, Any], local_secret: str = "") -> str:
    connector_type = subscription.get("connector_type")
    if connector_type == "api_key_env":
        ref = str(subscription.get("credential_ref") or "").strip()
        return os.getenv(ref, "") if ref else ""
    if connector_type == "api_key_local":
        return local_secret
    return ""


def codex_cli_ready(subscription: dict[str, Any] | None = None) -> dict[str, Any]:
    command = "codex"
    if subscription:
        command = str(subscription.get("credential_ref") or "codex").strip() or "codex"
    path = shutil.which(command)
    status: dict[str, Any] = {
        "ok": bool(path),
        "command": command,
        "path": path or "",
    }
    if path:
        try:
            result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5, check=False)
            status["version"] = (result.stdout or result.stderr).strip()
        except Exception as exc:  # pragma: no cover - depends on host binary behavior
            status["version_error"] = str(exc)
    return status


def codex_status() -> dict[str, Any]:
    default = codex_cli_ready()
    return {
        "codex_cli_available": default["ok"],
        "codex_cli_path": default["path"],
        "codex_cli_version": default.get("version", ""),
        "openai_cli_available": bool(shutil.which("openai")),
        "openai_cli_path": shutil.which("openai") or "",
    }


def oracle_status() -> dict[str, Any]:
    return {
        "oracle_helper_available": HERMES_AGENT_PYTHON.exists() and PRO_ORACLE_MODULE.exists(),
        "hermes_agent_python": str(HERMES_AGENT_PYTHON),
        "pro_oracle_module": str(PRO_ORACLE_MODULE),
        "node24_available": NODE24.exists(),
        "node24_path": str(NODE24),
        "oracle_cli_available": ORACLE_CLI.exists(),
        "oracle_cli_path": str(ORACLE_CLI),
        "manual_login_profile_exists": ORACLE_PROFILE.exists(),
        "manual_login_profile": str(ORACLE_PROFILE),
        "default_model": "gpt-5.5-pro",
    }


def codex_cli_run(*, subscription: dict[str, Any], model: str, prompt: str, timeout: int = 900) -> dict[str, Any]:
    ready = codex_cli_ready(subscription)
    if not ready["ok"]:
        raise ValueError(f"Codex CLI command not found: {ready['command']}")
    metadata = subscription.get("metadata") or {}
    template = metadata.get("codex_args") if isinstance(metadata, dict) else None
    if not isinstance(template, list) or not all(isinstance(item, str) for item in template):
        template = ["exec", "--model", "{model}", "{prompt}"]
    args = [part.format(model=model, prompt=prompt) for part in template]
    result = subprocess.run(
        [ready["path"], *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "command": ready["command"],
        "path": ready["path"],
        "args_template": template,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def pro_oracle_run(*, prompt: str, model: str = "gpt-5.5-pro", wait_seconds: int = 45, cwd: str | None = None) -> dict[str, Any]:
    status = oracle_status()
    if not status["oracle_helper_available"]:
        raise ValueError("Hermes pro_oracle helper is not available on this host.")
    raw_args = shlex.join(["--model", model, "--wait", str(wait_seconds), prompt])
    helper = """
import json, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
sys.path.insert(0, payload["hermes_agent_dir"])
from hermes_cli.pro_oracle import run_pro_command
print(run_pro_command(payload["raw_args"], cwd=payload.get("cwd") or None))
""".strip()
    payload = {
        "hermes_agent_dir": str(HERMES_AGENT_DIR),
        "raw_args": raw_args,
        "cwd": cwd,
    }
    result = subprocess.run(
        [str(HERMES_AGENT_PYTHON), "-c", helper],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(HERMES_AGENT_DIR),
        timeout=max(30, wait_seconds + 45),
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "model": model,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def openai_compatible_chat(
    *,
    subscription: dict[str, Any],
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    timeout: int = 90,
) -> dict[str, Any]:
    base_url = str(subscription.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("This provider needs a base_url for OpenAI-compatible chat completions.")
    if not api_key:
        raise ValueError("No API key is available for this provider.")
    if not model:
        raise ValueError("No model was selected.")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "HTTP-Referer": "http://127.0.0.1:8765",
            "X-Title": "Helmrail Local",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            body = json.loads(raw)
            text = _extract_chat_text(body)
            return {
                "ok": True,
                "status_code": response.status,
                "model": model,
                "provider": subscription.get("provider"),
                "response_text": text,
                "raw": body,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body: Any = json.loads(raw)
        except Exception:
            body = raw
        return {
            "ok": False,
            "status_code": exc.code,
            "model": model,
            "provider": subscription.get("provider"),
            "error": body,
        }


def _extract_chat_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)
