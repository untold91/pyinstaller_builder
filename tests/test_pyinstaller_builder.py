"""Tests for PyInstaller arguments, metadata, and process execution."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pyinstaller_builder.config import BuildConfig
from pyinstaller_builder.pyinstaller_builder import PyInstallerBuilder


def test_arguments_include_all_options_and_preserve_spaces(project: Path) -> None:
    """Include configured options and keep paths containing spaces intact."""
    config = BuildConfig.load(project)
    args = PyInstallerBuilder(config, platform_name="linux").arguments()
    assert "--onefile" in args
    assert "--windowed" in args
    assert ["--paths", str(project / "src")] == args[args.index("--paths") : args.index("--paths") + 2]
    assert [
        "--add-data",
        f"{project / 'assets'}:assets",
    ] == args[args.index("--add-data") : args.index("--add-data") + 2]
    assert ["--collect-all", "example_plugin"] == args[
        args.index("--collect-all") : args.index("--collect-all") + 2
    ]
    assert ["--hidden-import", "example_plugin.backend"] == args[
        args.index("--hidden-import") : args.index("--hidden-import") + 2
    ]
    assert ["--icon", str(project / "app.ico")] == args[
        args.index("--icon") : args.index("--icon") + 2
    ]
    assert str(project / "src" / "example app" / "main.py") == args[-1]
    assert "--version-file" not in args


def test_debug_onedir_and_windows_version_file_flags(project: Path) -> None:
    """Select debug and onedir flags and include Windows version metadata."""
    path = project / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('build-type = "release"', 'build-type = "debug"')
                    .replace('bundle = "onefile"', 'bundle = "onedir"'), encoding="utf-8")
    args = PyInstallerBuilder(BuildConfig.load(project), platform_name="win32").arguments()
    assert "--onedir" in args
    assert "--console" in args
    assert "--windowed" not in args
    assert args[args.index("--version-file") + 1] == str(project / "build" / "version_info.txt")
    assert args[args.index("--add-data") + 1] == f"{project / 'assets'}:assets"


def test_build_uses_active_interpreter_and_no_shell(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run PyInstaller with the active interpreter without invoking a shell."""
    seen: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = command
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("pyinstaller_builder.pyinstaller_builder.subprocess.run", run)
    PyInstallerBuilder(BuildConfig.load(project), platform_name="linux").build()
    assert seen["command"][:3] == [sys.executable, "-m", "PyInstaller"]
    assert seen["kwargs"] == {"check": True, "cwd": project}
    assert "shell" not in seen["kwargs"]


def test_build_propagates_pyinstaller_failure(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Propagate a non-zero PyInstaller process result to the caller."""
    def run(command: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr("pyinstaller_builder.pyinstaller_builder.subprocess.run", run)
    with pytest.raises(subprocess.CalledProcessError):
        PyInstallerBuilder(BuildConfig.load(project), platform_name="linux").build()
