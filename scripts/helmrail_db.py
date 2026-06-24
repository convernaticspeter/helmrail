#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / ".local" / "share" / "helmrail" / "helmrail.sqlite"
DEFAULT_SNAPSHOT_DIR = Path.home() / ".local" / "share" / "helmrail" / "snapshots"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _backup_sqlite(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Database not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def snapshot(db_path: Path, snapshot_dir: Path) -> Path:
    target = snapshot_dir / f"helmrail-{_timestamp()}.sqlite"
    _backup_sqlite(db_path, target)
    return target


def restore(snapshot_path: Path, db_path: Path, *, yes: bool = False, pre_restore_snapshot: bool = True) -> Path | None:
    if not yes:
        raise RuntimeError("Refusing restore without --yes")
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    safety_snapshot = None
    if db_path.exists() and pre_restore_snapshot:
        safety_snapshot = db_path.with_name(f"{db_path.stem}.pre-restore-{_timestamp()}{db_path.suffix}")
        _backup_sqlite(db_path, safety_snapshot)
    _backup_sqlite(snapshot_path, db_path)
    return safety_snapshot


def list_snapshots(snapshot_dir: Path) -> list[Path]:
    if not snapshot_dir.exists():
        return []
    return sorted(snapshot_dir.glob("helmrail-*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual Helmrail SQLite snapshot/restore helper.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite DB path (default: {DEFAULT_DB})")
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
        help=f"Snapshot directory (default: {DEFAULT_SNAPSHOT_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot", help="Create a live-safe SQLite snapshot")
    sub.add_parser("list", help="List available snapshots")
    restore_parser = sub.add_parser("restore", help="Restore a snapshot into the DB path")
    restore_parser.add_argument("snapshot", type=Path, help="Snapshot file to restore")
    restore_parser.add_argument("--yes", action="store_true", help="Required acknowledgement for restore")
    restore_parser.add_argument("--no-pre-restore-snapshot", action="store_true", help="Skip safety snapshot of current DB")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            target = snapshot(args.db.expanduser(), args.snapshot_dir.expanduser())
            print(target)
            return 0
        if args.command == "list":
            for item in list_snapshots(args.snapshot_dir.expanduser()):
                print(item)
            return 0
        if args.command == "restore":
            safety = restore(
                args.snapshot.expanduser(),
                args.db.expanduser(),
                yes=args.yes,
                pre_restore_snapshot=not args.no_pre_restore_snapshot,
            )
            if safety:
                print(f"pre_restore_snapshot={safety}")
            print(f"restored={args.db.expanduser()}")
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
