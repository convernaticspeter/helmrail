# Data contribution design

Helmrail is self-hosted first. Raw traces stay local unless an admin/user explicitly exports or contributes a redacted bundle.

## Principles

1. No default upload.
2. Redaction/anonymization runs locally.
3. Contribution is explicit opt-in.
4. Users can preview the bundle before anything leaves their instance.
5. Contribution samples use a random detached sample id, not the local trace id.

## v0.1 behavior

The prototype implements:

- local SQLite raw trace storage
- deterministic redaction for common identifiers/secrets
- contribution preview endpoint
- no automatic upload

## Redaction examples

The preview pipeline masks:

- email addresses
- phone-like numbers
- common API key/token/password assignments
- OpenAI-style `sk-...` tokens
- GitHub-style `gh*_...` tokens
- Sakana-style `fish_...` tokens
- common URL tracking/query secrets
- local filesystem paths

## Intended future bundle shape

```json
{
  "schema_version": "0.1",
  "sample_id": "sample_random",
  "created_at_bucket": "2026-06",
  "source": {
    "helmrail_version": "0.1.0",
    "contribution_mode": "manual-export-preview",
    "consent_version": "draft-0.1"
  },
  "task": {
    "category": "unknown",
    "language": "unknown",
    "sensitivity_after_redaction": "medium-review-required"
  },
  "routing": {
    "router_family": "prototype-deterministic",
    "worker_classes": [],
    "workflow_shape": "single"
  },
  "observations": {
    "latency_bucket": "unknown",
    "cost_bucket": "none",
    "tool_use_shape": "none",
    "success_signal": "unknown",
    "failure_mode": "unknown"
  }
}
```

## Non-goals in v0.1

- no automatic upload
- no hosted contribution account
- no training
- no claim that deterministic redaction is sufficient for all sensitive data

Human review remains required before contribution.
