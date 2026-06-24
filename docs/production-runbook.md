# Helmrail internal production runbook

Scope: local/internal Helmrail on Peter's Mac, loopback-only at `127.0.0.1:8765`.

This is not a public SaaS runbook. Keep it small and operational.

## Current service

- Launchd label: `eu.convernatics.helmrail.local`
- App root: `/Users/theo/Projects/helmrail`
- Runner: `/Users/theo/Library/Application Support/Helmrail/run-local.sh`
- API: `http://127.0.0.1:8765`
- DB: `~/.local/share/helmrail/helmrail.sqlite`
- Logs:
  - stdout: `~/.local/state/helmrail/stdout.log`
  - stderr: `~/.local/state/helmrail/stderr.log`

## Internal start/stop/check

```bash
launchctl list | grep -i helmrail
launchctl kickstart -k "gui/$(id -u)/eu.convernatics.helmrail.local"
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/eu.convernatics.helmrail.local.plist
curl -s http://127.0.0.1:8765/health | python3 -m json.tool
```

Expected `/health` basics:

```json
{
  "ok": true,
  "service": "helmrail",
  "auth_required": true,
  "limits": {
    "max_provider_calls": 8,
    "max_parallel_workers": 3,
    "provider_timeout_seconds": 120,
    "max_output_tokens": 16384
  }
}
```

## Runtime caps

Caps are intentionally simple. They prevent one user-facing request from silently fanning out into too many paid upstream model calls. The default output cap is deliberately roomy (`16384`); if a deliberate task needs more and the provider credit limit allows it, raise `HELMRAIL_MAX_OUTPUT_TOKENS` up to `65536`.

Configured via env:

```bash
HELMRAIL_MAX_PROVIDER_CALLS=8
HELMRAIL_MAX_PARALLEL_WORKERS=3
HELMRAIL_PROVIDER_TIMEOUT_SECONDS=120
HELMRAIL_MAX_OUTPUT_TOKENS=16384
```

For internal pilot:

| Alias | Suggested cap posture |
|---|---|
| `helmrail-fast` | direct/single-provider path where possible |
| `helmrail-auto` / `helmrail-coordinator` | default cap: 8 calls, 3 parallel workers |
| `helmrail-ultra` | allowed for deliberate tasks only; still capped |

If a cap blocks execution, trace metadata contains `budget.provider_calls_blocked > 0`.

## Pre-update snapshot, not backup theater

Before schema/routing changes or dependency updates, create a manual SQLite snapshot:

```bash
python scripts/helmrail_db.py snapshot
```

List snapshots:

```bash
python scripts/helmrail_db.py list
```

Restore only when you mean it:

```bash
python scripts/helmrail_db.py restore ~/.local/share/helmrail/snapshots/helmrail-YYYYMMDD-HHMMSS.sqlite --yes
```

Restore creates a `*.pre-restore-...sqlite` safety copy of the current DB first.

No rotating backup daemon is required for the pilot. Add real retention/backups only once feedback/training data has clear durable value.

## Update procedure

```bash
cd /Users/theo/Projects/helmrail
git status --short --branch
python scripts/helmrail_db.py snapshot
git pull --ff-only
. .venv/bin/activate
python -m compileall -q app tests scripts
pytest -q
launchctl kickstart -k "gui/$(id -u)/eu.convernatics.helmrail.local"
curl -s http://127.0.0.1:8765/health | python3 -m json.tool
```

Then run a one-item canary smoke:

```bash
python scripts/run_canaries.py --limit 1
```

For a file-only check without provider calls:

```bash
python scripts/run_canaries.py --dry-run
```

## Rollback procedure

```bash
cd /Users/theo/Projects/helmrail
git log --oneline -5
git reset --hard <known-good-sha>
. .venv/bin/activate
python -m compileall -q app tests scripts
pytest -q
launchctl kickstart -k "gui/$(id -u)/eu.convernatics.helmrail.local"
curl -s http://127.0.0.1:8765/health | python3 -m json.tool
```

Restore DB only if the rollback needs it. Do not restore DB reflexively.

## Hermes smoke

Configure a Hermes custom provider pointing at Helmrail, then test without switching the global default:

```bash
hermes chat -q 'Reply with exactly: HERMES_HELMRAIL_OK' \
  --provider custom:helmrail \
  -m helmrail-coordinator \
  --toolsets safe \
  -Q
```

Expected exact response:

```text
HERMES_HELMRAIL_OK
```

## Internal pilot acceptance

Before using Helmrail as a regular work provider:

- [ ] `/health` returns `ok:true`, auth enabled, caps visible.
- [ ] `pytest -q` passes locally.
- [ ] Latest GitHub CI is green.
- [ ] `python scripts/helmrail_db.py snapshot` creates a readable SQLite snapshot.
- [ ] `python scripts/run_canaries.py --dry-run` loads 20 canaries.
- [ ] One live canary returns a non-empty answer and a trace id.
- [ ] Hermes custom-provider smoke returns the exact marker.
- [ ] Trace export does not leak obvious emails, phones, run IDs, or token fragments.

## Operational boundaries

Allowed during pilot:

- coding review / planning
- strategy and copy drafts
- Google Ads / CRO diagnosis without live account mutation
- research synthesis
- internal second opinions

Not allowed without explicit approval:

- sending external messages
- live ads mutations
- automatic uploads of training data
- public exposure beyond loopback
- unreviewed customer-data exports
