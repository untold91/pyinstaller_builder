from __future__ import annotations

from pathlib import Path

import pytest

from pyinstaller_builder.config import BuildConfig
from pyinstaller_builder.exceptions import (
    ConfigurationConflictError,
    ConfigurationError,
    LegacyConfigurationError,
    ProjectFileError,
    UninitializedConfigurationError,
)


def _write_config(root: Path, body: str) -> None:
    (root / "pyproject.toml").write_text(body, encoding="utf-8")


def test_load_full_config_resolves_paths_and_defaults_version(project: Path) -> None:
    config = BuildConfig.load(project)
    assert config.version == "1.2.3"
    assert config.entry_point == project / "src" / "example app" / "main.py"
    assert config.source_paths == (project / "src",)
    assert config.icon == project / "app.ico"
    assert config.data_files[0].source == project / "assets"
    assert config.data_files[0].target == "assets"
    assert config.executable_name.startswith("example-app_v1.2.3_")


def test_minimal_settings_use_documented_defaults(project: Path) -> None:
    _write_config(
        project,
        """
[project]
name = "minimal-app"
version = "0.2.0"
[tool.pyinstaller_builder]
initialized = true
entry-point = "src/example app/main.py"
""".lstrip(),
    )
    config = BuildConfig.load(project)
    assert config.build_type == "release"
    assert config.bundle == "onefile"
    assert config.icon is None
    assert config.source_paths == ()


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ("", "not initialized"),
        ("entry-point = 12", "entry-point is required"),
        ('entry-point = "missing.py"', "existing file"),
        ('entry-point = "src/example app/main.py"\nbuild-type = "fast"', "build-type must be"),
        ('entry-point = "src/example app/main.py"\nbundle = "zip"', "bundle must be"),
        ('entry-point = "src/example app/main.py"\nhidden-imports = [""]', "non-empty strings"),
        (
            'entry-point = "src/example app/main.py"\n[[tool.pyinstaller_builder.data-files]]\nsource = "assets"\ntarget = "../outside"',
            "stay inside",
        ),
    ],
)
def test_invalid_settings_report_key(project: Path, settings: str, message: str) -> None:
    if settings:
        _write_config(
            project,
            '[project]\nname = "app"\nversion = "1.0.0"\n[tool.pyinstaller_builder]\ninitialized = true\n'
            + settings,
        )
    else:
        _write_config(project, '[project]\nname = "app"\nversion = "1.0.0"\n')
    error_type = UninitializedConfigurationError if not settings else ConfigurationError
    with pytest.raises(error_type, match=message):
        BuildConfig.load(project)


def test_dynamic_project_version_requires_explicit_override(project: Path) -> None:
    _write_config(
        project,
        """
[project]
name = "dynamic-app"
dynamic = ["version"]
[tool.pyinstaller_builder]
initialized = true
entry-point = "src/example app/main.py"
""".lstrip(),
    )
    with pytest.raises(ConfigurationError, match=r"version is dynamic"):
        BuildConfig.load(project)

    with (project / "pyproject.toml").open("a", encoding="utf-8") as stream:
        stream.write('version = "3.0.0"\n')
    assert BuildConfig.load(project).version == "3.0.0"


def test_invalid_version_and_executable_name_are_rejected(project: Path) -> None:
    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    _write_config(project, text.replace('version = "1.2.3"', 'version = "None"'))
    with pytest.raises(ConfigurationError, match="valid numeric version"):
        BuildConfig.load(project)

    _write_config(
        project,
        text.replace('bundle = "onefile"', 'bundle = "onefile"\nexecutable-name = "../unsafe"'),
    )
    with pytest.raises(ConfigurationError, match="executable-name"):
        BuildConfig.load(project)


def test_missing_or_false_initialized_flag_requires_setup(project: Path) -> None:
    path = project / "pyproject.toml"
    body = path.read_text(encoding="utf-8")
    path.write_text(body.replace("initialized = true\n", ""), encoding="utf-8")
    with pytest.raises(UninitializedConfigurationError, match="not initialized"):
        BuildConfig.load(project)

    path.write_text(body.replace("initialized = true", "initialized = false"), encoding="utf-8")
    with pytest.raises(UninitializedConfigurationError, match="not initialized"):
        BuildConfig.load(project)


def test_initialized_must_be_boolean(project: Path) -> None:
    path = project / "pyproject.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("initialized = true", 'initialized = "yes"'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="initialized must be a boolean"):
        BuildConfig.load(project)


def test_legacy_namespace_requires_explicit_migration(project: Path) -> None:
    path = project / "pyproject.toml"
    body = path.read_text(encoding="utf-8").replace(
        "[tool.pyinstaller_builder]", "[tool.buildtools]"
    ).replace(
        "[[tool.pyinstaller_builder.data-files]]",
        "[[tool.buildtools.data-files]]",
    )
    path.write_text(body, encoding="utf-8")
    with pytest.raises(LegacyConfigurationError, match="pyinstaller_builder init"):
        BuildConfig.load(project)


def test_both_configuration_namespaces_report_conflict(project: Path) -> None:
    path = project / "pyproject.toml"
    body = path.read_text(encoding="utf-8")
    path.write_text(
        body + '\n[tool.buildtools]\ninitialized = true\nentry-point = "src/example app/main.py"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationConflictError, match="resolve the conflict"):
        BuildConfig.load(project)


def test_malformed_toml_and_missing_pyproject_are_actionable(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Invalid TOML"):
        BuildConfig.load(tmp_path)
    (tmp_path / "pyproject.toml").unlink()
    with pytest.raises(ProjectFileError, match="pyproject.toml was not found"):
        BuildConfig.load(tmp_path)
