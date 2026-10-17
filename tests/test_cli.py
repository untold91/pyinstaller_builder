"""Tests for command-line parsing, dispatch, and failure handling."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pyinstaller_builder.cli import main
from pyinstaller_builder.pyinstaller_builder import CleanResult, CleanUtility, PyInstallerBuilder


def test_top_level_and_subcommand_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Show help for the CLI and its build subcommand."""
    with pytest.raises(SystemExit) as top:
        main(["--help"])
    assert top.value.code == 0
    assert "init" in capsys.readouterr().out
    with pytest.raises(SystemExit) as command:
        main(["build", "--help"])
    assert command.value.code == 0
    assert "--project-dir" in capsys.readouterr().out


def test_build_configuration_error_has_nonzero_exit_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Return an actionable error when build configuration is uninitialized."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "host-app"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    code = main(["build", "--project-dir", str(tmp_path)])
    assert code == 2
    error = capsys.readouterr().err
    assert "not initialized" in error
    assert "pyinstaller_builder init" in error
    assert "Traceback" not in error


def test_clean_dispatch_and_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dispatch clean in dry-run mode and preserve the output directory."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "host-app"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "dist").mkdir()
    assert main(["clean", "--project-dir", str(tmp_path), "--dry-run"]) == 0
    assert (tmp_path / "dist").is_dir()
    assert "Would remove" in capsys.readouterr().out


def test_init_refuses_noninteractive_use(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Reject initialization when the CLI cannot prompt for input."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "host-app"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    assert main(["init", "--project-dir", str(tmp_path)]) == 2
    assert "requires an interactive terminal" in capsys.readouterr().err


def test_build_dispatch_success(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dispatch a valid build and report its success."""
    monkeypatch.setattr(PyInstallerBuilder, "build", lambda _builder: None)
    assert main(["build", "--project-dir", str(project)]) == 0
    assert "Build succeeded" in capsys.readouterr().out


def test_build_dispatch_returns_pyinstaller_exit_code(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Return the PyInstaller process exit code when a build fails."""
    def fail(_builder: PyInstallerBuilder) -> None:
        raise subprocess.CalledProcessError(9, ["PyInstaller"])

    monkeypatch.setattr(PyInstallerBuilder, "build", fail)
    assert main(["build", "--project-dir", str(project)]) == 9
    assert "failed with exit code 9" in capsys.readouterr().err


@pytest.mark.parametrize("location", ["host", "nested", "submodule"])
def test_cli_discovers_host_root_from_working_directory(
    tmp_path: Path,
    location: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discover the host root from the current host, nested, or submodule path."""
    host = tmp_path / "host"
    host.mkdir()
    (host / "pyproject.toml").write_text(
        '[project]\nname = "host-app"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    if location == "host":
        cwd = host
    elif location == "nested":
        cwd = host / "src" / "host_app"
        cwd.mkdir(parents=True)
    else:
        cwd = host / "tools" / "pyinstaller_builder"
        cwd.mkdir(parents=True)
        (cwd / "pyproject.toml").write_text(
            '[project]\nname = "pyinstaller_builder"\nversion = "1.0.0"\n\n'
            '[project.scripts]\npyinstaller_builder = "pyinstaller_builder.cli:main"\n',
            encoding="utf-8",
        )
        (cwd / "src" / "pyinstaller_builder").mkdir(parents=True)

    seen: list[Path] = []
    monkeypatch.setattr(Path, "cwd", classmethod(lambda _cls: cwd))
    monkeypatch.setattr(
        CleanUtility,
        "clean",
        lambda root, dry_run=False: (
            seen.append(root) or CleanResult((), (), ())
        ),
    )
    assert main(["clean"]) == 0
    assert seen == [host]


def test_interactive_build_initializes_then_builds_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Initialize an unconfigured host interactively, then build it once."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "host-app"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    calls: list[Path] = []
    monkeypatch.setattr(PyInstallerBuilder, "build", lambda builder: calls.append(builder.config.project_root))
    answers = iter(["y", "", "", "", "", "", "y"])
    assert main(
        ["build", "--project-dir", str(tmp_path)],
        input_fn=lambda _prompt: next(answers),
        interactive=True,
    ) == 0
    assert calls == [tmp_path]
    assert "Build succeeded" in capsys.readouterr().out
    assert "initialized = true" in pyproject.read_text(encoding="utf-8")


def test_declining_auto_initialization_does_not_write_or_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Leave configuration and build state untouched when initialization is declined."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "host-app"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    original = pyproject.read_text(encoding="utf-8")
    monkeypatch.setattr(
        PyInstallerBuilder,
        "build",
        lambda _builder: pytest.fail("build must not run after declining initialization"),
    )
    assert main(
        ["build", "--project-dir", str(tmp_path)],
        input_fn=lambda _prompt: "n",
        interactive=True,
    ) == 2
    assert pyproject.read_text(encoding="utf-8") == original
    assert "pyinstaller_builder init" in capsys.readouterr().out


def test_eof_during_auto_init_prompt_cancels_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cancel automatic initialization cleanly when input reaches EOF."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "host-app"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    original = pyproject.read_text(encoding="utf-8")

    def eof(_prompt: str) -> str:
        raise EOFError

    assert main(
        ["build", "--project-dir", str(tmp_path)],
        input_fn=eof,
        interactive=True,
    ) == 130
    assert pyproject.read_text(encoding="utf-8") == original
    assert "cancelled without changes" in capsys.readouterr().err


def test_noninteractive_build_does_not_prompt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report uninitialized configuration without prompting in noninteractive mode."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "host-app"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    assert main(["build", "--project-dir", str(tmp_path)], interactive=False) == 2
    error = capsys.readouterr().err
    assert "not initialized" in error
    assert "pyinstaller_builder init" in error


def test_malformed_host_toml_does_not_trigger_auto_init(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Avoid interactive repair when the host TOML is malformed."""
    pyproject = tmp_path / "pyproject.toml"
    original = "[project\n"
    pyproject.write_text(original, encoding="utf-8")

    def unexpected_prompt(_prompt: str) -> str:
        pytest.fail("malformed TOML must not start interactive initialization")

    assert main(
        ["build", "--project-dir", str(tmp_path)],
        input_fn=unexpected_prompt,
        interactive=True,
    ) == 2
    assert pyproject.read_text(encoding="utf-8") == original
    assert "Invalid TOML" in capsys.readouterr().err


def test_initialized_but_invalid_build_config_offers_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Offer repair for invalid initialized settings and continue after correction."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "host-app"
version = "1.0.0"

[tool.pyinstaller_builder]
initialized = true
entry-point = "missing.py"
""".lstrip(),
        encoding="utf-8",
    )
    calls: list[Path] = []
    monkeypatch.setattr(
        PyInstallerBuilder,
        "build",
        lambda builder: calls.append(builder.config.project_root),
    )
    answers = iter(["y", "u", "entry-point", "", "y"])
    assert main(
        ["build", "--project-dir", str(tmp_path)],
        input_fn=lambda _prompt: next(answers),
        interactive=True,
    ) == 0
    assert calls == [tmp_path]
    assert "initialized = true" in pyproject.read_text(encoding="utf-8")
    assert "Build succeeded" in capsys.readouterr().out
