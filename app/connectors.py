from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any


PROVIDER_PRESETS: list[dict[str, Any]] = [
    {
        "id": "openai_codex",
        "label": "OpenAI / Codex",
        "provider": "openai",
        "plan": "Codex / OpenAI API",
        "connector_type": "api_key_local",
        "base_url": "https://api.openai.com/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["codex", "gpt-4.1"],
        "help": "Paste an OpenAI API key. Use your available Codex/coding model name in the workbench.",
    },
    {
        "id": "anthropic",
        "label": "Anthropic Claude",
        "provider": "anthropic",
        "plan": "Claude API",
        "connector_type": "api_key_local",
        "base_url": "https://api.anthropic.com",
        "api_style": "native_pending",
        "model_aliases": ["claude"],
        "help": "Stores the Anthropic key now. Native Claude runtime wiring is separate from Codex workbench.",
    },
    {
        "id": "google_gemini",
        "label": "Google Gemini",
        "provider": "google",
        "plan": "Gemini API",
        "connector_type": "api_key_local",
        "base_url": "https://generativelanguage.googleapis.com",
        "api_style": "native_pending",
        "model_aliases": ["gemini"],
        "help": "Stores the Gemini key now. Native Gemini runtime wiring is separate from Codex workbench.",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "provider": "openrouter",
        "plan": "OpenRouter API",
        "connector_type": "api_key_local",
        "base_url": "https://openrouter.ai/api/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["openrouter-auto"],
        "help": "OpenAI-compatible router. Enter any model you enabled in OpenRouter.",
    },
    {
        "id": "xai",
        "label": "xAI / Grok",
        "provider": "xai",
        "plan": "xAI API",
        "connector_type": "api_key_local",
        "base_url": "https://api.x.ai/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["grok"],
        "help": "OpenAI-compatible xAI endpoint.",
    },
    {
        "id": "mistral",
        "label": "Mistral",
        "provider": "mistral",
        "plan": "Mistral API",
        "connector_type": "api_key_local",
        "base_url": "https://api.mistral.ai/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["mistral"],
        "help": "OpenAI-compatible Mistral endpoint.",
    },
    {
        "id": "groq",
        "label": "Groq",
        "provider": "groq",
        "plan": "Groq API",
        "connector_type": "api_key_local",
        "base_url": "https://api.groq.com/openai/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["groq"],
        "help": "OpenAI-compatible Groq endpoint.",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "provider": "deepseek",
        "plan": "DeepSeek API",
        "connector_type": "api_key_local",
        "base_url": "https://api.deepseek.com/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["deepseek"],
        "help": "OpenAI-compatible DeepSeek endpoint.",
    },
    {
        "id": "together",
        "label": "Together AI",
        "provider": "together",
        "plan": "Together API",
        "connector_type": "api_key_local",
        "base_url": "https://api.together.xyz/v1",
        "api_style": "openai_compatible",
        "model_aliases": ["together"],
        "help": "OpenAI-compatible Together endpoint.",
    },
    {
        "id": "perplexity",
        "label": "Perplexity",
        "provider": "perplexity",
        "plan": "Perplexity API",
        "connector_type": "api_key_local",
        "base_url": "https://api.perplexity.ai",
        "api_style": "openai_compatible",
        "model_aliases": ["perplexity"],
        "help": "OpenAI-compatible Perplexity endpoint.",
    },
    {
        "id": "custom_openai",
        "label": "Custom OpenAI-compatible",
        "provider": "custom",
        "plan": "Custom API",
        "connector_type": "api_key_local",
        "base_url": "",
        "api_style": "openai_compatible",
        "model_aliases": [],
        "help": "Use for local/self-hosted or provider-specific OpenAI-compatible base URLs.",
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
    if subscription.get("connector_type") == "api_key_env":
        ref = str(subscription.get("credential_ref") or "").strip()
        return os.getenv(ref, "") if ref else ""
    return local_secret


def codex_status() -> dict[str, Any]:
    command = shutil.which("codex")
    status: dict[str, Any] = {
        "codex_cli_available": bool(command),
        "codex_cli_path": command or "",
        "openai_cli_available": bool(shutil.which("openai")),
        "openai_cli_path": shutil.which("openai") or "",
    }
    if command:
        try:
            result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=5, check=False)
            status["codex_cli_version"] = (result.stdout or result.stderr).strip()
        except Exception as exc:  # pragma: no cover - depends on host binary behavior
            status["codex_cli_version_error"] = str(exc)
    return status


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
