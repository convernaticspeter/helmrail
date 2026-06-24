from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .training import build_training_sample


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 10:
        return "••••"
    return f"{secret[:4]}…{secret[-4:]}"


class TraceStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS training_samples (
                    sample_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    sample_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    account_label TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    connector_type TEXT NOT NULL,
                    credential_ref TEXT NOT NULL,
                    base_url TEXT NOT NULL DEFAULT '',
                    secret_value TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    model_aliases_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "subscriptions", "base_url", "base_url TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "subscriptions", "secret_value", "secret_value TEXT NOT NULL DEFAULT ''")
            conn.commit()

    def save_trace(
        self,
        *,
        endpoint: str,
        model: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        run_id = f"run_{uuid4().hex}"
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO traces (run_id, created_at, endpoint, model, input_json, output_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    created_at,
                    endpoint,
                    model,
                    json.dumps(input_payload, ensure_ascii=False),
                    json.dumps(output_payload, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            sample_id = f"sample_{uuid4().hex}"
            sample = build_training_sample(
                sample_id=sample_id,
                created_at=created_at,
                endpoint=endpoint,
                model=model,
                input_payload=input_payload,
                output_payload=output_payload,
                metadata=metadata or {},
            )
            conn.execute(
                """
                INSERT INTO training_samples (sample_id, created_at, run_id, schema_version, sample_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sample_id,
                    created_at,
                    run_id,
                    str(sample.get("schema_version") or "unknown"),
                    json.dumps(sample, ensure_ascii=False),
                    json.dumps(
                        {
                            "run_id": run_id,
                            "endpoint": endpoint,
                            "model": model,
                            "source": "auto_generated_from_local_trace",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.commit()
        return run_id

    def get_trace(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM traces WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "endpoint": row["endpoint"],
            "model": row["model"],
            "input": json.loads(row["input_json"]),
            "output": json.loads(row["output_json"]),
            "metadata": json.loads(row["metadata_json"]),
        }

    def list_traces(self, limit: int = 25) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, created_at, endpoint, model, metadata_json FROM traces ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "endpoint": row["endpoint"],
                "model": row["model"],
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def _training_sample_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        sample = json.loads(row["sample_json"])
        return {
            "sample_id": row["sample_id"],
            "created_at": row["created_at"],
            "schema_version": row["schema_version"],
            "sample": sample,
        }

    def list_training_samples(self, limit: int = 25) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sample_id, created_at, schema_version, sample_json FROM training_samples ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._training_sample_from_row(row) for row in rows]

    def get_training_sample(self, sample_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sample_id, created_at, schema_version, sample_json FROM training_samples WHERE sample_id = ?",
                (sample_id,),
            ).fetchone()
        return None if row is None else self._training_sample_from_row(row)

    def get_training_sample_for_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sample_id, created_at, schema_version, sample_json FROM training_samples WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return None if row is None else self._training_sample_from_row(row)

    def create_subscription(
        self,
        *,
        provider: str,
        account_label: str,
        plan: str = "",
        connector_type: str,
        credential_ref: str = "",
        base_url: str = "",
        secret_value: str = "",
        enabled: bool = True,
        status: str = "configured",
        model_aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        subscription_id = f"sub_{uuid4().hex}"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    id, created_at, updated_at, provider, account_label, plan,
                    connector_type, credential_ref, base_url, secret_value,
                    enabled, status, model_aliases_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription_id,
                    now,
                    now,
                    provider,
                    account_label,
                    plan,
                    connector_type,
                    credential_ref,
                    base_url,
                    secret_value,
                    1 if enabled else 0,
                    status,
                    json.dumps(model_aliases or [], ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
        subscription = self.get_subscription(subscription_id)
        if subscription is None:
            raise RuntimeError("subscription insert failed")
        return subscription

    def list_subscriptions(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM subscriptions ORDER BY provider, account_label LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._subscription_from_row(row) for row in rows]

    def get_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
        if row is None:
            return None
        return self._subscription_from_row(row)

    def get_subscription_secret(self, subscription_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT secret_value FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
        return "" if row is None else str(row["secret_value"] or "")

    def update_subscription(self, subscription_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "provider",
            "account_label",
            "plan",
            "connector_type",
            "credential_ref",
            "base_url",
            "secret_value",
            "enabled",
            "status",
            "model_aliases",
            "metadata",
        }
        filtered = {key: value for key, value in changes.items() if key in allowed and value is not None}
        if not filtered:
            return self.get_subscription(subscription_id)

        columns: list[str] = ["updated_at = ?"]
        values: list[Any] = [_utc_now()]
        for key, value in filtered.items():
            if key == "enabled":
                columns.append("enabled = ?")
                values.append(1 if value else 0)
            elif key == "model_aliases":
                columns.append("model_aliases_json = ?")
                values.append(json.dumps(value or [], ensure_ascii=False))
            elif key == "metadata":
                columns.append("metadata_json = ?")
                values.append(json.dumps(value or {}, ensure_ascii=False))
            else:
                columns.append(f"{key} = ?")
                values.append(value)
        values.append(subscription_id)

        with self._connect() as conn:
            conn.execute(f"UPDATE subscriptions SET {', '.join(columns)} WHERE id = ?", values)
            conn.commit()
        return self.get_subscription(subscription_id)

    def delete_subscription(self, subscription_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
            conn.commit()
        return cursor.rowcount > 0

    def _subscription_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        secret = str(row["secret_value"] or "")
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "provider": row["provider"],
            "account_label": row["account_label"],
            "plan": row["plan"],
            "connector_type": row["connector_type"],
            "credential_ref": row["credential_ref"],
            "base_url": row["base_url"],
            "has_secret": bool(secret),
            "secret_preview": _mask_secret(secret),
            "enabled": bool(row["enabled"]),
            "status": row["status"],
            "model_aliases": json.loads(row["model_aliases_json"]),
            "metadata": json.loads(row["metadata_json"]),
        }
