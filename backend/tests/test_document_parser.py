from pathlib import Path

import document_parser as dp


def test_parse_txt(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")
    assert dp.parse_document(f) == "hello world"


def test_parse_markdown(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("# Title\ncontent", encoding="utf-8")
    assert dp.parse_document(f) == "# Title\ncontent"


def test_parse_python(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("print('hi')", encoding="utf-8")
    assert dp.parse_document(f) == "print('hi')"


def test_parse_missing_file(tmp_path: Path):
    assert dp.parse_document(tmp_path / "nope.txt") == ""


def test_parse_unsupported(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"\x00\x01\x02")
    assert dp.parse_document(f) == ""
