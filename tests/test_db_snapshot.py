import sqlite3

from scripts.helmrail_db import list_snapshots, restore, snapshot


def _write_db(path, value):
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS items (value TEXT NOT NULL)")
        con.execute("DELETE FROM items")
        con.execute("INSERT INTO items (value) VALUES (?)", (value,))
        con.commit()
    finally:
        con.close()


def _read_value(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT value FROM items").fetchone()[0]
    finally:
        con.close()


def test_snapshot_and_restore_roundtrip(tmp_path):
    db = tmp_path / "helmrail.sqlite"
    snapshots = tmp_path / "snapshots"
    _write_db(db, "before")

    snap = snapshot(db, snapshots)
    assert snap.exists()
    assert snap.parent == snapshots
    assert _read_value(snap) == "before"

    _write_db(db, "after")
    safety = restore(snap, db, yes=True)
    assert safety is not None
    assert safety.exists()
    assert _read_value(safety) == "after"
    assert _read_value(db) == "before"
    assert snap in list_snapshots(snapshots)


def test_restore_requires_yes(tmp_path):
    db = tmp_path / "helmrail.sqlite"
    snapshots = tmp_path / "snapshots"
    _write_db(db, "before")
    snap = snapshot(db, snapshots)
    _write_db(db, "after")

    try:
        restore(snap, db)
    except RuntimeError as exc:
        assert "--yes" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("restore should require --yes")
    assert _read_value(db) == "after"
