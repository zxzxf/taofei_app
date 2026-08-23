from pathlib import Path

import db


def test_memory_table_exists():
    db.DB_FILE = Path(__file__).parent / "test_memory_db.db"
    conn = None
    try:
        db.init_db()
        conn = db._get_conn()
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        indexes = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "memory_entries" in tables
        assert "idx_memory_ws" in indexes
    finally:
        if conn is not None:
            conn.close()
        try:
            db.DB_FILE.unlink(missing_ok=True)
        except PermissionError:
            pass
