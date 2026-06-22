from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import Settings
from .redaction import redact_json, redact_text
from .store import TraceStore


class ContributionPreviewRequest(BaseModel):
    run_id: str = Field(..., description="Local Helmrail trace id")


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            return str(content)
    return ""


def _prototype_answer(prompt: str) -> str:
    clean = redact_text(prompt).strip()
    preview = clean[:700] if clean else "(empty input)"
    return (
        "Helmrail prototype response. No upstream worker is configured in this build yet; "
        "this API is currently proving the OpenAI-compatible surface, local trace store, "
        "and anonymized contribution pipeline.\n\n"
        f"Received input preview: {preview}"
    )


def _require_auth(settings: Settings):
    async def dependency(authorization: str | None = Header(default=None)) -> None:
        if not settings.require_auth:
            return
        expected = f"Bearer {settings.api_key}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    return dependency


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = TraceStore(settings.db_path)
    auth = _require_auth(settings)

    app = FastAPI(
        title="Helmrail API",
        version=settings.version,
        description="Self-hosted switchboard prototype for subscription/API-based model access.",
    )
    app.state.settings = settings
    app.state.store = store

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "helmrail",
            "version": settings.version,
            "mode": "prototype-wrapper",
            "trace_store": "sqlite",
            "auth_required": settings.require_auth,
        }

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        created = 1760000000
        return {
            "object": "list",
            "data": [
                {
                    "id": "helmrail-fast",
                    "object": "model",
                    "created": created,
                    "owned_by": "helmrail",
                    "description": "Prototype single-worker/router-compatible model alias.",
                },
                {
                    "id": "helmrail-ultra",
                    "object": "model",
                    "created": created,
                    "owned_by": "helmrail",
                    "description": "Prototype conductor-compatible model alias.",
                },
            ],
        }

    @app.post("/v1/chat/completions", dependencies=[Depends(auth)])
    def chat_completions(payload: dict[str, Any], response: Response) -> dict[str, Any]:
        if payload.get("stream"):
            raise HTTPException(status_code=400, detail="Streaming is not implemented in the prototype")
        model = str(payload.get("model") or "helmrail-fast")
        messages = payload.get("messages") or []
        if not isinstance(messages, list):
            raise HTTPException(status_code=422, detail="messages must be a list")

        prompt = _last_user_text(messages)
        answer = _prototype_answer(prompt)
        created = int(time.time())
        completion_id = f"chatcmpl_{uuid4().hex}"
        output = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "system_fingerprint": "helmrail-prototype-v0.1",
        }
        run_id = store.save_trace(
            endpoint="/v1/chat/completions",
            model=model,
            input_payload=payload,
            output_payload=output,
            metadata={
                "router_family": "prototype-deterministic",
                "workflow_shape": "single",
                "worker_classes": [],
                "success_signal": "unknown",
            },
        )
        response.headers["X-Helmrail-Trace-Id"] = run_id
        output["helmrail_trace_id"] = run_id
        return output

    @app.post("/v1/responses", dependencies=[Depends(auth)])
    def responses(payload: dict[str, Any], response: Response) -> dict[str, Any]:
        if payload.get("stream"):
            raise HTTPException(status_code=400, detail="Streaming is not implemented in the prototype")
        model = str(payload.get("model") or "helmrail-fast")
        raw_input = payload.get("input", "")
        prompt = raw_input if isinstance(raw_input, str) else str(raw_input)
        answer = _prototype_answer(prompt)
        created = int(time.time())
        response_id = f"resp_{uuid4().hex}"
        output = {
            "id": response_id,
            "object": "response",
            "created_at": created,
            "status": "completed",
            "model": model,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": answer}],
                }
            ],
            "output_text": answer,
        }
        run_id = store.save_trace(
            endpoint="/v1/responses",
            model=model,
            input_payload=payload,
            output_payload=output,
            metadata={
                "router_family": "prototype-deterministic",
                "workflow_shape": "single",
                "worker_classes": [],
                "success_signal": "unknown",
            },
        )
        response.headers["X-Helmrail-Trace-Id"] = run_id
        output["helmrail_trace_id"] = run_id
        return output

    @app.get("/v1/traces", dependencies=[Depends(auth)])
    def traces(limit: int = 25) -> dict[str, Any]:
        return {"object": "list", "data": store.list_traces(limit=limit)}

    @app.get("/v1/traces/{run_id}", dependencies=[Depends(auth)])
    def trace_detail(run_id: str) -> dict[str, Any]:
        trace = store.get_trace(run_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return trace

    @app.post("/v1/contributions/preview", dependencies=[Depends(auth)])
    def contribution_preview(request: ContributionPreviewRequest) -> dict[str, Any]:
        trace = store.get_trace(request.run_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        created_at = trace["created_at"]
        month_bucket = created_at[:7] if created_at else datetime.now(timezone.utc).strftime("%Y-%m")
        input_redacted = redact_json(trace["input"])
        output_redacted = redact_json(trace["output"])
        metadata = trace.get("metadata") or {}
        sample = {
            "schema_version": "0.1",
            "sample_id": f"sample_{uuid4().hex}",
            "created_at_bucket": month_bucket,
            "source": {
                "helmrail_version": settings.version,
                "contribution_mode": "manual-export-preview",
                "consent_version": "draft-0.1",
            },
            "task": {
                "category": "unknown",
                "language": "unknown",
                "sensitivity_after_redaction": "medium-review-required",
                "input_redacted": input_redacted,
            },
            "routing": {
                "router_family": metadata.get("router_family", "prototype-deterministic"),
                "worker_classes": metadata.get("worker_classes", []),
                "workflow_shape": metadata.get("workflow_shape", "single"),
            },
            "observations": {
                "latency_bucket": "unknown",
                "cost_bucket": "none",
                "tool_use_shape": "none",
                "success_signal": metadata.get("success_signal", "unknown"),
                "failure_mode": "unknown",
            },
            "outputs": {
                "output_redacted": output_redacted,
            },
            "warnings": [
                "Preview only: no data has been uploaded.",
                "Human review is required before contribution.",
            ],
        }
        return sample

    return app


app = create_app()
