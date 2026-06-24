# Data contribution design

Helmrail is self-hosted first. Raw traces stay local unless an admin/user explicitly exports or contributes a redacted bundle.

## Principles

1. No default upload.
2. Redaction/anonymization runs locally.
3. Contribution is explicit opt-in.
4. Users can preview/export the bundle before anything leaves their instance.
5. Contribution samples use a random detached `sample_id`, not the local trace id.
6. Current redaction is applied again at read/export time so older samples benefit from later hardening.

## Current local behavior

The prototype implements:

- local SQLite raw trace storage
- automatic anonymized training samples for each saved trace
- feedback labels on anonymized samples
- derived preference pairs from anonymized samples
- JSONL exports for samples and preference pairs
- no automatic upload

## Redaction examples

The preview/export pipeline masks:

- email addresses
- phone-like numbers
- common API key/token/password assignments
- OpenAI-style `sk-...` tokens
- GitHub-style `gh*_...` tokens
- Sakana-style `fish_...` tokens
- structured `*-token` / `*-secret` fragments
- common URL tracking/query secrets
- local filesystem paths
- internal smoke-test markers

Human review remains required before any contribution/upload. Deterministic redaction is not a legal guarantee for arbitrary sensitive records.

## Local records

### Raw trace

Raw traces are operational/debug records and may include local run IDs and internal routing details. They stay local.

### Training sample

Training samples are detached/anonymized records with:

```json
{
  "schema_version": "0.4",
  "sample_id": "sample_random",
  "created_at_bucket": "2026-06",
  "source": {
    "contribution_mode": "local-auto-anonymized",
    "upload_state": "local_only_not_uploaded"
  },
  "task": {
    "category": "unknown",
    "sensitivity_after_redaction": "medium-review-required"
  },
  "routing": {
    "router_family": "llm-coordinator",
    "workflow_shape": "fugu-style-executed-multi-agent-as-model"
  },
  "privacy": {
    "contains_local_run_id": false,
    "raw_trace_included": false,
    "review_required_before_upload": true
  }
}
```

### Feedback label

Feedback labels attach to samples, not raw traces:

- `accepted`
- `rejected`
- `edited`
- `user_corrected`
- `good`
- `bad`
- `partial`
- `unknown`

Corrections, notes, and metadata are redacted before storage.

### Preference pair

Preference pairs are derived only from anonymized samples:

- `verifier`: accepted worker output > rejected worker output
- `synthesizer`: synthesized output > candidate output
- `race_winner`: first successful race output > non-winner output as operational signal
- `human_feedback`: corrected human output > selected/final model output

Preference pairs must not require or emit local raw trace IDs.

## Endpoints

```text
GET  /v1/training-samples
GET  /v1/training-samples/{sample_id}
GET  /v1/training-exports/jsonl
POST /v1/training-samples/{sample_id}/feedback
GET  /v1/training-samples/{sample_id}/feedback
GET  /v1/training-samples/{sample_id}/preference-pairs
GET  /v1/training-preference-pairs
GET  /v1/training-preference-exports/jsonl
POST /v1/contributions/preview
```

## Non-goals in the internal pilot

- no automatic upload
- no hosted contribution account
- no public training data intake
- no claim that deterministic redaction is sufficient for all sensitive data
- no irreversible detachment/upload workflow yet
