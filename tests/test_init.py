from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from pyinstaller_builder.exceptions import (
    ConfigurationError,
    InitializationCancelled,
    PyInstallerBuilderError,
)
from pyinstaller_builder.init import initialize


def _answering(values: list[str]):
    answers = iter(values)
    return lambda _prompt: next(answers)


def test_init_preserves_existing_toml_and_adds_configuration(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    original = (
        "# keep this comment\n"
        "[build-system]\nrequires = ['setuptools>=68']\nbuild-backend = 'setuptools.build_meta'\n\n"
        "[project]\nname = 'sample'\nversion = '1.0.0'\n\n"
        "[tool.other]\nflag = true\n"
    )
    pyproject.write_text(original, encoding="utf-8")
    changed = initialize(
        tmp_path,
        input_fn=_answering(["", "", "", "", "", "y"]),
        output_fn=lambda _message: None,
    )
    assert changed
    result = pyproject.read_text(encoding="utf-8")
    assert "# keep this comment" in result
    assert "[build-system]" in result
    assert "[project]" in result
    assert "[tool.other]" in result
    parsed = tomlkit.parse(result)
    assert parsed["tool"]["pyinstaller_builder"]["entry-point"] == "src/main.py"
    assert parsed["tool"]["pyinstaller_builder"]["source-paths"] == ["src"]
    assert parsed["tool"]["pyinstaller_builder"]["initialized"] is True


def test_existing_config_can_be_kept_without_writing(project: Path) -> None:
    path = project / "pyproject.toml"
    original = path.read_text(encoding="utf-8")
    changed = initialize(
        project,
        input_fn=_answering(["k"]),
        output_fn=lambda _message: None,
    )
    assert not changed
    assert path.read_text(encoding="utf-8") == original


def test_existing_config_selective_update_preserves_other_settings(project: Path) -> None:
    path = project / "pyproject.toml"
    changed = initialize(
        project,
        input_fn=_answering(["u", "build-type", "debug", "y"]),
        output_fn=lambda _message: None,
    )
    assert changed
    result = tomlkit.parse(path.read_text(encoding="utf-8"))["tool"]["pyinstaller_builder"]
    assert result["build-type"] == "debug"
    assert result["bundle"] == "onefile"
    assert result["hidden-imports"] == ["example_plugin.backend"]


def test_existing_config_replacement_requires_final_confirmation(project: Path) -> None:
    path = project / "pyproject.toml"
    changed = initialize(
        project,
        input_fn=_answering(["r", "", "", "", "", "", "y"]),
        output_fn=lambda _message: None,
    )
    assert changed
    result = tomlkit.parse(path.read_text(encoding="utf-8"))["tool"]["pyinstaller_builder"]
    assert result["initialized"] is True
    assert result["build-type"] == "release"
    assert result["hidden-imports"] == []
    assert "company-name" not in result


def test_existing_config_can_update_version_without_touching_other_keys(project: Path) -> None:
    path = project / "pyproject.toml"
    changed = initialize(
        project,
        input_fn=_answering(["u", "version", "2.0.0", "y"]),
        output_fn=lambda _message: None,
    )
    assert changed
    result = tomlkit.parse(path.read_text(encoding="utf-8"))["tool"]["pyinstaller_builder"]
    assert result["version"] == "2.0.0"
    assert result["entry-point"] == "src/example app/main.py"
    assert result["bundle"] == "onefile"


def test_legacy_settings_migrate_after_two_confirmations(project: Path) -> None:
    path = project / "pyproject.toml"
    original = path.read_text(encoding="utf-8")
    legacy = original.replace(
        "[tool.pyinstaller_builder]", "[tool.buildtools]"
    ).replace(
        "[[tool.pyinstaller_builder.data-files]]",
        "[[tool.buildtools.data-files]]",
    )
    path.write_text(legacy, encoding="utf-8")

    assert initialize(
        project,
        input_fn=_answering(["y", "y"]),
        output_fn=lambda _message: None,
    )
    migrated_text = path.read_text(encoding="utf-8")
    migrated = tomlkit.parse(migrated_text)
    settings = migrated["tool"]["pyinstaller_builder"]
    assert settings["initialized"] is True
    assert settings["data-files"][0]["source"] == "assets"
    assert "buildtools" not in migrated["tool"]
    assert "[tool.custom]" in migrated_text


def test_declining_legacy_migration_keeps_file_unchanged(project: Path) -> None:
    path = project / "pyproject.toml"
    legacy = path.read_text(encoding="utf-8").replace(
        "[tool.pyinstaller_builder]", "[tool.buildtools]"
    ).replace(
        "[[tool.pyinstaller_builder.data-files]]",
        "[[tool.buildtools.data-files]]",
    )
    path.write_text(legacy, encoding="utf-8")
    original = path.read_text(encoding="utf-8")

    assert not initialize(
        project,
        input_fn=_answering(["n"]),
        output_fn=lambda _message: None,
    )
    assert path.read_text(encoding="utf-8") == original


def test_both_config_tables_require_explicit_conflict_resolution(project: Path) -> None:
    path = project / "pyproject.toml"
    canonical = path.read_text(encoding="utf-8")
    legacy = canonical.replace(
        "[tool.pyinstaller_builder]", "[tool.buildtools]"
    ).replace(
        "[[tool.pyinstaller_builder.data-files]]",
        "[[tool.buildtools.data-files]]",
    )
    legacy += """

[tool.pyinstaller_builder]
initialized = true
entry-point = "src/example app/main.py"
source-paths = ["src"]
build-type = "debug"
bundle = "onedir"
"""
    path.write_text(legacy, encoding="utf-8")
    original = path.read_text(encoding="utf-8")

    assert not initialize(
        project,
        input_fn=_answering(["c"]),
        output_fn=lambda _message: None,
    )
    assert path.read_text(encoding="utf-8") == original

    assert initialize(
        project,
        input_fn=_answering(["n", "y"]),
        output_fn=lambda _message: None,
    )
    result = tomlkit.parse(path.read_text(encoding="utf-8"))
    assert "buildtools" not in result["tool"]
    assert result["tool"]["pyinstaller_builder"]["build-type"] == "debug"
    assert result["tool"]["pyinstaller_builder"]["bundle"] == "onedir"


def test_cancel_does_not_modify_file(project: Path) -> None:
    path = project / "pyproject.toml"
    original = path.read_text(encoding="utf-8")
    with pytest.raises(InitializationCancelled):
        initialize(project, input_fn=_answering(["r", "", "", "", "", "", "n"]))
    assert path.read_text(encoding="utf-8") == original


def test_eof_is_friendly_cancellation(project: Path) -> None:
    def eof(_prompt: str) -> str:
        raise EOFError

    with pytest.raises(InitializationCancelled, match="not changed"):
        initialize(project, input_fn=eof)


def test_init_requires_existing_pyproject(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Initialize the Python project first"):
        initialize(tmp_path)


def test_failed_atomic_replace_leaves_original_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    path = tmp_path / "pyproject.toml"
    original = '[project]\nname = "sample"\nversion = "1.0.0"\n'
    path.write_text(original, encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("pyinstaller_builder.init.os.replace", fail_replace)
    with pytest.raises(PyInstallerBuilderError, match="simulated replace failure"):
        initialize(
            tmp_path,
            input_fn=_answering(["", "", "", "", "", "y"]),
            output_fn=lambda _message: None,
        )
    assert path.read_text(encoding="utf-8") == original
