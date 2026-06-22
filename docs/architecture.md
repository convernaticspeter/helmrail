# Architecture

Helmrail v0.1 is intentionally small:

```text
OpenAI-compatible HTTP API
  -> prototype router
  -> local trace store
  -> local contribution preview/redaction
```

There are no upstream model workers in the first deployed prototype. The purpose is to prove deployment, API shape, trace capture, and anonymized contribution scaffolding before connector complexity is added.

## Planned connector boundary

Future worker connectors should implement:

- provider/account identity
- health check
- invoke request
- timeout/error classification
- cost/latency metadata
- trace-safe output packaging

Connector types:

- OpenAI-compatible API
- Anthropic API
- Gemini API
- browser subscription connector
- local model connector

## Data boundary

Raw traces are local. Contribution previews are redacted locally. Upload is not implemented in v0.1.
