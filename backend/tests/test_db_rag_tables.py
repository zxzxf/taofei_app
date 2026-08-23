from pathlib import Path

import db


def test_rag_tables_exist():
    db.DB_FILE = Path(__file__).parent / "test_taofei_app.db"
    conn = None
    try:
        db.init_db()
        conn = db._get_conn()
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "knowledge_bases" in tables
        assert "knowledge_chunks" in tables
    finally:
        if conn is not None:
            conn.close()
        try:
            db.DB_FILE.unlink(missing_ok=True)
        except PermissionError:
            pass
