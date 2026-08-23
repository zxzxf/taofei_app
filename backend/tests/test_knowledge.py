from pathlib import Path

import db
import knowledge


def test_create_list_delete_kb(tmp_path: Path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    kb = knowledge.create_kb("测试库", "desc")
    assert kb["name"] == "测试库"
    assert kb["status"] == "ready"
    kbs = knowledge.list_kbs()
    assert len(kbs) == 1
    assert kbs[0]["id"] == kb["id"]
    assert kbs[0]["chunk_count"] == 0
    assert knowledge.delete_kb(kb["id"]) is True
    assert len(knowledge.list_kbs()) == 0


def test_delete_missing_kb(tmp_path: Path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    assert knowledge.delete_kb("not-exist") is False


def test_upload_missing_file(tmp_path: Path):
    db.DB_FILE = tmp_path / "test.db"
    db.init_db()
    kb = knowledge.create_kb("测试库")
    try:
        knowledge.upload_file(kb["id"], str(tmp_path / "nope.txt"))
        assert False, "应当抛出 FileNotFoundError"
    except FileNotFoundError:
        pass
