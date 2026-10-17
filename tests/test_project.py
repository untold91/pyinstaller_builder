"""Tests for locating the host project and skipping tool packaging roots."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyinstaller_builder.exceptions import ProjectFileError
from pyinstaller_builder.project import resolve_project_root


def _write_project(root: Path, name: str = "host-app") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )


def _write_tool_checkout(root: Path) -> None:
    _write_project(root, name="pyinstaller_builder")
    path = root / "pyproject.toml"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[project.scripts]\npyinstaller_builder = "pyinstaller_builder.cli:main"\n'
        )
    (root / "src" / "pyinstaller_builder").mkdir(parents=True)


def test_discovers_host_root_from_project_root_and_nested_directory(tmp_path: Path) -> None:
    """Find the nearest host root from its root and a nested directory."""
    host = tmp_path / "host"
    _write_project(host)
    nested = host / "src" / "host_app"
    nested.mkdir(parents=True)

    assert resolve_project_root(start_dir=host) == host
    assert resolve_project_root(start_dir=nested) == host


def test_skips_submodule_packaging_pyproject_and_finds_host(tmp_path: Path) -> None:
    """Skip a submodule's own packaging metadata and find its host project."""
    host = tmp_path / "host"
    submodule = host / "tools" / "pyinstaller_builder"
    nested = submodule / "src"
    _write_project(host)
    _write_tool_checkout(submodule)
    nested.mkdir(exist_ok=True)

    assert resolve_project_root(start_dir=nested) == host


def test_submodule_directory_without_host_requires_explicit_root(tmp_path: Path) -> None:
    """Require an explicit host root when no parent project exists."""
    submodule = tmp_path / "pyinstaller_builder"
    _write_tool_checkout(submodule)
    with pytest.raises(ProjectFileError, match="pass --project-dir"):
        resolve_project_root(start_dir=submodule)


def test_explicit_host_project_root_is_used(tmp_path: Path) -> None:
    """Use an explicitly selected host even if a nested project is present."""
    host = tmp_path / "host"
    _write_project(host)
    nested = host / "tools" / "pyinstaller_builder"
    _write_project(nested, name="pyinstaller_builder")

    assert resolve_project_root(host / ".") == host


def test_host_project_can_use_distribution_name_without_being_skipped(tmp_path: Path) -> None:
    """Do not mistake a host project name for the tool's packaging project."""
    _write_project(tmp_path, name="pyinstaller_builder")
    assert resolve_project_root(start_dir=tmp_path) == tmp_path


def test_tool_checkout_is_not_accepted_as_host_root() -> None:
    """Reject the tool checkout when explicitly supplied as the host root."""
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(ProjectFileError, match="not a host project"):
        resolve_project_root(repository)
