"""_resolve_python_exe 回归测试：打包环境下优先命中部署根的 .venv。"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import agent_tools


def test_packaged_resolves_deploy_venv():
    r"""Electron 打包结构：部署根\resources\backend\exe，.venv 在部署根。"""
    tmp = Path(tempfile.mkdtemp())
    exe_dir = tmp / "deploy" / "resources" / "backend"
    exe_dir.mkdir(parents=True)
    fake_exe = exe_dir / "TaofeiAPI.exe"
    fake_exe.write_bytes(b"MZ")
    venv_py = tmp / "deploy" / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_bytes(b"MZ")

    orig_frozen = getattr(sys, "frozen", False)
    orig_executable = sys.executable
    sys.frozen = True  # type: ignore[attr-defined]
    sys.executable = str(fake_exe)  # type: ignore[assignment]
    try:
        with patch("agent_tools._is_usable_python", side_effect=lambda p: p == str(venv_py)):
            resolved = agent_tools._resolve_python_exe()
    finally:
        sys.frozen = orig_frozen
        sys.executable = orig_executable

    assert resolved == str(venv_py), f"未优先命中部署根 .venv: {resolved}"


def test_dev_mode_returns_sys_executable():
    """开发模式（非 frozen）直接返回当前解释器。"""
    orig_frozen = getattr(sys, "frozen", False)
    orig_executable = sys.executable
    sys.frozen = False  # type: ignore[attr-defined]
    sys.executable = "C:/dev/.venv/Scripts/python.exe"  # type: ignore[assignment]
    try:
        assert agent_tools._resolve_python_exe() == "C:/dev/.venv/Scripts/python.exe"
    finally:
        sys.frozen = orig_frozen
        sys.executable = orig_executable
