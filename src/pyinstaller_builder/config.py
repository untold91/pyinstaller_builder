"""Parsing and validation for the [tool.buildtools] configuration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from pyinstaller_builder.exceptions import (
    ConfigurationError,
    ProjectFileError,
    UninitializedConfigurationError,
)

BUILD_TYPES = ("release", "debug")
BUNDLE_MODES = ("onefile", "onedir")
_VERSION_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|\.post\d+|\.dev\d+)?(?:\+[A-Za-z0-9.-]+)?$"
)
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")


@dataclass(frozen=True)
class DataFile:
    """A project file or directory and its destination in the bundled app."""

    source: Path
    target: str


@dataclass(frozen=True)
class BuildConfig:
    """Validated build settings with paths resolved against the project root."""

    project_root: Path
    initialized: bool
    name: str
    executable_name: str
    version: str
    entry_point: Path
    source_paths: tuple[Path, ...]
    build_type: str
    bundle: str
    icon: Path | None
    data_files: tuple[DataFile, ...]
    collect_packages: tuple[str, ...]
    hidden_imports: tuple[str, ...]
    company_name: str
    author: str
    product_name: str
    file_description: str
    internal_name: str

    @classmethod
    def load(cls, project_root: Path) -> BuildConfig:
        """Read pyproject.toml and validate all settings needed for a build."""
        root = project_root.resolve()
        pyproject = root / "pyproject.toml"
        try:
            document = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProjectFileError(
                f"pyproject.toml was not found in {root}; initialize the Python project first"
            ) from exc
        except OSError as exc:
            raise ProjectFileError(f"Could not read {pyproject}: {exc}") from exc
        except ParseError as exc:
            raise ProjectFileError(
                f"Invalid TOML in {pyproject}: {exc}. Repair it manually before running init."
            ) from exc
        tool = document.get("tool")
        settings = tool.get("buildtools") if isinstance(tool, Mapping) else None
        if not isinstance(settings, Mapping):
            raise UninitializedConfigurationError(
                "This host project is not initialized for BuildTools; it has no "
                "[tool.buildtools] configuration. Run 'buildtools-python init' to set it up."
            )
        if "initialized" not in settings:
            raise UninitializedConfigurationError(
                "This host project is not initialized for BuildTools. "
                "Run 'buildtools-python init' to set it up."
            )
        initialized = settings["initialized"]
        if initialized is False:
            raise UninitializedConfigurationError(
                "This host project is not initialized for BuildTools. "
                "Run 'buildtools-python init' to set it up."
            )
        if not isinstance(initialized, bool):
            raise ConfigurationError(
                "[tool.buildtools].initialized must be a boolean (true or false)"
            )
        return cls.from_document(document, root)

    @classmethod
    def from_document(cls, document: Mapping[str, Any], project_root: Path) -> BuildConfig:
        """Validate an already-parsed TOML document (also used by init)."""
        project = _table(document.get("project"), "[project]")
        project_name = _required_string(project, "name", "[project].name")

        tool_value = document.get("tool")
        if tool_value is None:
            raise ConfigurationError("[tool.buildtools] table is required")
        tool = _table(tool_value, "[tool]")
        if tool.get("buildtools") is None:
            raise ConfigurationError("[tool.buildtools] table is required")
        settings = _table(tool.get("buildtools"), "[tool.buildtools]")
        initialized = settings.get("initialized")
        if not isinstance(initialized, bool):
            raise ConfigurationError(
                "[tool.buildtools].initialized must be a boolean (true or false)"
            )
        if not initialized:
            raise UninitializedConfigurationError(
                "This host project is not initialized for BuildTools. "
                "Run 'buildtools-python init' to set it up."
            )

        version_value = settings.get("version")
        if version_value is None:
            version_value = project.get("version")
            if version_value is None:
                dynamic = project.get("dynamic", [])
                if isinstance(dynamic, list) and "version" in dynamic:
                    reason = "[project].version is dynamic"
                else:
                    reason = "[project].version is not set"
                raise ConfigurationError(
                    f"[tool.buildtools].version is required because {reason}; set an explicit version"
                )
            version_key = "[project].version"
        else:
            version_key = "[tool.buildtools].version"
        version = _required_string({version_key: version_value}, version_key, version_key)
        if not _VERSION_PATTERN.fullmatch(version):
            raise ConfigurationError(f"{version_key} must be a valid numeric version such as '1.2.3'")

        internal_name = _optional_string(settings, "internal-name", project_name)
        _validate_name(internal_name, "[tool.buildtools].internal-name")
        executable_name = _optional_string(settings, "executable-name", "")
        if executable_name:
            _validate_name(executable_name, "[tool.buildtools].executable-name")
        else:
            executable_name = f"{internal_name}_v{version}_{target_architecture()}"

        entry_point = _existing_path(
            project_root,
            settings.get("entry-point"),
            "[tool.buildtools].entry-point",
            expected="file",
        )
        source_paths = _path_list(
            project_root, settings.get("source-paths", []), "[tool.buildtools].source-paths"
        )
        build_type = _optional_string(settings, "build-type", "release")
        if build_type not in BUILD_TYPES:
            raise ConfigurationError(
                f"[tool.buildtools].build-type must be one of {BUILD_TYPES}, got {build_type!r}"
            )
        bundle = _optional_string(settings, "bundle", "onefile")
        if bundle not in BUNDLE_MODES:
            raise ConfigurationError(
                f"[tool.buildtools].bundle must be one of {BUNDLE_MODES}, got {bundle!r}"
            )

        icon_value = settings.get("icon")
        icon = (
            _existing_path(project_root, icon_value, "[tool.buildtools].icon", expected="file")
            if icon_value is not None
            else None
        )
        data_files = _data_files(project_root, settings.get("data-files", []))
        collect_packages = _string_list(
            settings.get("collect-packages", []), "[tool.buildtools].collect-packages"
        )
        hidden_imports = _string_list(
            settings.get("hidden-imports", []), "[tool.buildtools].hidden-imports"
        )

        return cls(
            project_root=project_root.resolve(),
            initialized=initialized,
            name=project_name,
            executable_name=executable_name,
            version=version,
            entry_point=entry_point,
            source_paths=tuple(source_paths),
            build_type=build_type,
            bundle=bundle,
            icon=icon,
            data_files=tuple(data_files),
            collect_packages=tuple(collect_packages),
            hidden_imports=tuple(hidden_imports),
            company_name=_optional_string(settings, "company-name", ""),
            author=_optional_string(settings, "author", ""),
            product_name=_optional_string(settings, "product-name", project_name),
            file_description=_optional_string(settings, "file-description", project_name),
            internal_name=internal_name,
        )


def load_build_config(project_root: Path) -> BuildConfig:
    """Convenience function for loading a project-root BuildConfig."""
    return BuildConfig.load(project_root)


def target_architecture() -> str:
    """Return the running interpreter's normalized architecture label."""
    import sysconfig

    machine = sysconfig.get_platform().lower().rsplit("-", 1)[-1]
    return {
        "win32": "x86",
        "i386": "x86",
        "i686": "x86",
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine, machine)


def is_valid_version(value: str) -> bool:
    """Return whether value matches the numeric version form accepted by config."""
    return bool(_VERSION_PATTERN.fullmatch(value))


def is_valid_name(value: str) -> bool:
    """Return whether value is safe to use for a cross-platform executable name."""
    return (
        bool(_NAME_PATTERN.fullmatch(value))
        and not value.endswith((".", " "))
        and value not in {".", ".."}
    )


def normalize_data_target(value: Any, key: str) -> str:
    """Validate and normalize a relative bundle destination."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty relative path")
    normalized = value.strip().replace("\\", "/")
    target_path = Path(normalized)
    if (
        target_path.is_absolute()
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in target_path.parts
    ):
        raise ConfigurationError(f"{key} must stay inside the bundled application")
    return normalized


def _table(value: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{key} must be a TOML table")
    return value


def _required_string(table: Mapping[str, Any], key: str, display_key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{display_key} is required and must be a non-empty string")
    return value.strip()


def _optional_string(table: Mapping[str, Any], key: str, default: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigurationError(f"[tool.buildtools].{key} must be a string")
    value = value.strip()
    if key in {"product-name", "file-description"} and not value:
        raise ConfigurationError(f"[tool.buildtools].{key} must be a non-empty string")
    return value


def _validate_name(value: str, key: str) -> None:
    if not is_valid_name(value):
        raise ConfigurationError(
            f"{key} must be a valid executable name containing only letters, numbers, "
            "spaces, dots, underscores, or hyphens"
        )


def _existing_path(root: Path, value: Any, key: str, expected: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} is required and must be a non-empty path string")
    path = Path(value.strip())
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if expected == "file":
        valid = path.is_file()
    elif expected == "directory":
        valid = path.is_dir()
    else:
        valid = path.exists()
    if not valid:
        kind = {"file": "file", "directory": "directory", "any": "file or directory"}[expected]
        raise ConfigurationError(f"{key} must point to an existing {kind}: {path}")
    return path


def _path_list(root: Path, value: Any, key: str) -> list[Path]:
    if not isinstance(value, list):
        raise ConfigurationError(f"{key} must be an array of directory paths")
    return [
        _existing_path(root, item, f"{key}[{index}]", expected="directory")
        for index, item in enumerate(value)
    ]


def _string_list(value: Any, key: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigurationError(f"{key} must be an array of non-empty strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigurationError(f"{key} must contain only non-empty strings")
    return [item.strip() for item in value]


def _data_files(root: Path, value: Any) -> list[DataFile]:
    key = "[tool.buildtools].data-files"
    if not isinstance(value, list):
        raise ConfigurationError(f"{key} must be an array of tables")
    result: list[DataFile] = []
    for index, item in enumerate(value):
        entry_key = f"{key}[{index}]"
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"{entry_key} must be a table with 'source' and optional 'target'")
        source = _existing_path(root, item.get("source"), f"{entry_key}.source", expected="any")
        normalized_target = normalize_data_target(item.get("target", "."), f"{entry_key}.target")
        result.append(DataFile(source=source, target=normalized_target))
    return result
