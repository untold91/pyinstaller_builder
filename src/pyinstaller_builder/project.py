"""Host-project root discovery for installed and submodule use."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from pyinstaller_builder.exceptions import ProjectFileError

_DISTRIBUTION_NAME = "pyinstaller_builder"
_PACKAGE_DIRECTORY = Path(__file__).resolve().parent
_SOURCE_REPOSITORY_ROOT = (
    _PACKAGE_DIRECTORY.parent.parent
    if _PACKAGE_DIRECTORY.parent.name == "src"
    and (_PACKAGE_DIRECTORY.parent.parent / "pyproject.toml").is_file()
    else None
)


def resolve_project_root(
    project_dir: Path | None = None,
    *,
    start_dir: Path | None = None,
    require_pyproject: bool = True,
) -> Path:
    """Resolve the explicit host root or nearest host project above start_dir.

    The tool's own checkout is skipped during discovery, so invocation from a
    nested submodule directory can continue to the containing host project.
    """
    if project_dir is not None:
        root = project_dir.expanduser().resolve()
        if not root.is_dir():
            raise ProjectFileError(f"Project directory does not exist: {root}")
        if _is_tool_repository(root):
            raise ProjectFileError(
                f"{root} is the pyinstaller_builder tool repository, not a host project. "
                "Pass --project-dir with the host application's root."
            )
        return root

    current = (start_dir or Path.cwd()).expanduser().resolve()
    if not current.is_dir():
        current = current.parent
    if not require_pyproject:
        return current
    for candidate in (current, *current.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        if _is_tool_repository(candidate):
            continue
        if _is_tool_distribution_pyproject(pyproject):
            continue
        return candidate
    raise ProjectFileError(
        f"Could not find a host project's pyproject.toml from {current}. "
        "Run the command inside the host project or pass --project-dir PATH."
    )


def _is_tool_repository(root: Path) -> bool:
    return _SOURCE_REPOSITORY_ROOT is not None and root == _SOURCE_REPOSITORY_ROOT


def _is_tool_distribution_pyproject(path: Path) -> bool:
    try:
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
    except (OSError, ParseError):
        return False
    project: Any = document.get("project")
    if not isinstance(project, Mapping) or project.get("name") != _DISTRIBUTION_NAME:
        return False
    scripts = project.get("scripts")
    return (
        isinstance(scripts, Mapping)
        and scripts.get("pyinstaller_builder") == "pyinstaller_builder.cli:main"
        and (path.parent / "src" / "pyinstaller_builder").is_dir()
    )
