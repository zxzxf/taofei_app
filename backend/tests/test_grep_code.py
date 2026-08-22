"""grep_code 工具回归测试：path 参数对文件与目录均生效。"""

import tempfile
from pathlib import Path

import agent_tools


def _make_ws() -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "sub").mkdir()
    (tmp / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp / "sub" / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
    return tmp


def test_grep_file_path():
    """path 指向单文件时只搜索该文件。"""
    ws = _make_ws()
    r = agent_tools.grep_code(str(ws), "foo", path="a.py")
    assert "a.py" in r["observation"]
    assert "b.py" not in r["observation"]


def test_grep_dir_path():
    """path 指向目录时递归搜索。"""
    ws = _make_ws()
    r = agent_tools.grep_code(str(ws), "return", path="sub")
    assert "b.py" in r["observation"]


def test_grep_file_no_match():
    """单文件搜索无匹配时返回未找到提示。"""
    ws = _make_ws()
    r = agent_tools.grep_code(str(ws), "不存在的关键词", path="a.py")
    assert "未找到匹配" in r["observation"]


def test_grep_global():
    """无 path 时搜索整个工作空间。"""
    ws = _make_ws()
    r = agent_tools.grep_code(str(ws), "return")
    assert "a.py" in r["observation"]
    assert "b.py" in r["observation"]


def test_grep_missing_path():
    """path 指向不存在的文件时返回提示而非崩溃。"""
    ws = _make_ws()
    r = agent_tools.grep_code(str(ws), "foo", path="nope.py")
    assert "不存在" in r["observation"] or "未找到匹配" in r["observation"]
