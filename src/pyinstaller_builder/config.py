"""Parsing and validation for [tool.pyinstaller_builder] configuration."""

from __future__ import annotations

import re
import sysconfig
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from pyinstaller_builder.exceptions import (
    ConfigurationConflictError,
    ConfigurationError,
    LegacyConfigurationError,
    ProjectFileError,
    UninitializedConfigurationError,
)

CONFIG_TABLE = "pyinstaller_builder"
LEGACY_CONFIG_TABLE = "buildtools"
CONFIG_PREFIX = f"[tool.{CONFIG_TABLE}]"
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
class BuildOptions:
    """Validated PyInstaller-specific options."""

    source_paths: tuple[Path, ...]
    build_type: str
    bundle: str
    icon: Path | None
    data_files: tuple[DataFile, ...]
    collect_packages: tuple[str, ...]
    hidden_imports: tuple[str, ...]


@dataclass(frozen=True)
class BuildMetadata:
    """Validated application identity and Windows version metadata."""

    name: str
    version: str
    company_name: str
    author: str
    product_name: str
    file_description: str
    internal_name: str


@dataclass(frozen=True)
class BuildConfig:
    """Validated build settings with paths resolved against the project root."""

    project_root: Path
    initialized: bool
    executable_name: str
    entry_point: Path
    options: BuildOptions
    metadata: BuildMetadata

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
        legacy_settings = (
            tool.get(LEGACY_CONFIG_TABLE) if isinstance(tool, Mapping) else None
        )
        settings = tool.get(CONFIG_TABLE) if isinstance(tool, Mapping) else None
        if isinstance(legacy_settings, Mapping) and isinstance(settings, Mapping):
            raise ConfigurationConflictError(
                "Both [tool.buildtools] and [tool.pyinstaller_builder] exist. "
                "Run 'pyinstaller_builder init' and explicitly resolve the conflict."
            )
        if isinstance(legacy_settings, Mapping) and settings is None:
            raise LegacyConfigurationError(
                "Found legacy [tool.buildtools] configuration. "
                "Run 'pyinstaller_builder init' to review and migrate it."
            )
        if not isinstance(settings, Mapping):
            raise UninitializedConfigurationError(
                f"This host project is not initialized for {CONFIG_PREFIX}; "
                f"run 'pyinstaller_builder init' to set it up."
            )
        if "initialized" not in settings:
            raise UninitializedConfigurationError(
                f"This host project is not initialized for {CONFIG_PREFIX}. "
                "Run 'pyinstaller_builder init' to set it up."
            )
        initialized = settings["initialized"]
        if initialized is False:
            raise UninitializedConfigurationError(
                f"This host project is not initialized for {CONFIG_PREFIX}. "
                "Run 'pyinstaller_builder init' to set it up."
            )
        if not isinstance(initialized, bool):
            raise ConfigurationError(
                f"{CONFIG_PREFIX}.initialized must be a boolean (true or false)"
            )
        return cls.from_document(document, root)

    @classmethod
    def from_document(cls, document: Mapping[str, Any], project_root: Path) -> BuildConfig:
        """Validate an already-parsed TOML document (also used by init)."""
        project = _table(document.get("project"), "[project]")
        project_name = _required_string(project, "name", "[project].name")
        settings = _configuration_settings(document)
        initialized = _validate_initialized(settings)
        version = _configuration_version(project, settings)
        internal_name, executable_name = _application_names(settings, project_name, version)
        return cls(
            project_root=project_root.resolve(),
            initialized=initialized,
            executable_name=executable_name,
            entry_point=_existing_path(
                project_root,
                settings.get("entry-point"),
                f"{CONFIG_PREFIX}.entry-point",
                expected="file",
            ),
            options=_build_options(project_root, settings),
            metadata=_build_metadata(settings, project_name, version, internal_name),
        )

    @property
    def name(self) -> str:
        """Return the host project's package name."""
        return self.metadata.name

    @property
    def version(self) -> str:
        """Return the configured application version."""
        return self.metadata.version

    @property
    def source_paths(self) -> tuple[Path, ...]:
        """Return resolved source directories."""
        return self.options.source_paths

    @property
    def build_type(self) -> str:
        """Return the selected build type."""
        return self.options.build_type

    @property
    def bundle(self) -> str:
        """Return the selected bundle mode."""
        return self.options.bundle

    @property
    def icon(self) -> Path | None:
        """Return the configured icon, if any."""
        return self.options.icon

    @property
    def data_files(self) -> tuple[DataFile, ...]:
        """Return configured bundle data files."""
        return self.options.data_files

    @property
    def collect_packages(self) -> tuple[str, ...]:
        """Return packages selected for full collection."""
        return self.options.collect_packages

    @property
    def hidden_imports(self) -> tuple[str, ...]:
        """Return explicitly configured hidden imports."""
        return self.options.hidden_imports

    @property
    def company_name(self) -> str:
        """Return the configured company name."""
        return self.metadata.company_name

    @property
    def author(self) -> str:
        """Return the configured author."""
        return self.metadata.author

    @property
    def product_name(self) -> str:
        """Return the configured product name."""
        return self.metadata.product_name

    @property
    def file_description(self) -> str:
        """Return the configured file description."""
        return self.metadata.file_description

    @property
    def internal_name(self) -> str:
        """Return the configured internal application name."""
        return self.metadata.internal_name


def _configuration_settings(document: Mapping[str, Any]) -> Mapping[str, Any]:
    tool = _table(document.get("tool"), "[tool]")
    settings = tool.get(CONFIG_TABLE)
    if settings is None:
        raise ConfigurationError(f"{CONFIG_PREFIX} table is required")
    return _table(settings, CONFIG_PREFIX)


def _validate_initialized(settings: Mapping[str, Any]) -> bool:
    initialized = settings.get("initialized")
    if not isinstance(initialized, bool):
        raise ConfigurationError(
            f"{CONFIG_PREFIX}.initialized must be a boolean (true or false)"
        )
    if not initialized:
        raise UninitializedConfigurationError(
            f"This host project is not initialized for {CONFIG_PREFIX}. "
            "Run 'pyinstaller_builder init' to set it up."
        )
    return initialized


def _configuration_version(project: Mapping[str, Any], settings: Mapping[str, Any]) -> str:
    value = settings.get("version")
    key = f"{CONFIG_PREFIX}.version"
    if value is None:
        value = project.get("version")
        key = "[project].version"
        if value is None:
            dynamic = project.get("dynamic", [])
            reason = "is dynamic" if isinstance(dynamic, list) and "version" in dynamic else "is not set"
            raise ConfigurationError(
                f"{CONFIG_PREFIX}.version is required because [project].version {reason}; "
                "set an explicit version"
            )
    version = _required_string({key: value}, key, key)
    if not _VERSION_PATTERN.fullmatch(version):
        raise ConfigurationError(f"{key} must be a valid numeric version such as '1.2.3'")
    return version


def _application_names(
    settings: Mapping[str, Any], project_name: str, version: str
) -> tuple[str, str]:
    internal_name = _optional_string(settings, "internal-name", project_name)
    _validate_name(internal_name, f"{CONFIG_PREFIX}.internal-name")
    executable_name = _optional_string(settings, "executable-name", "")
    if executable_name:
        _validate_name(executable_name, f"{CONFIG_PREFIX}.executable-name")
    else:
        executable_name = f"{internal_name}_v{version}_{target_architecture()}"
    return internal_name, executable_name


def _build_options(project_root: Path, settings: Mapping[str, Any]) -> BuildOptions:
    build_type = _optional_string(settings, "build-type", "release")
    if build_type not in BUILD_TYPES:
        raise ConfigurationError(
            f"{CONFIG_PREFIX}.build-type must be one of {BUILD_TYPES}, got {build_type!r}"
        )
    bundle = _optional_string(settings, "bundle", "onefile")
    if bundle not in BUNDLE_MODES:
        raise ConfigurationError(
            f"{CONFIG_PREFIX}.bundle must be one of {BUNDLE_MODES}, got {bundle!r}"
        )
    icon_value = settings.get("icon")
    icon = (
        _existing_path(project_root, icon_value, f"{CONFIG_PREFIX}.icon", expected="file")
        if icon_value is not None
        else None
    )
    return BuildOptions(
        source_paths=tuple(
            _path_list(project_root, settings.get("source-paths", []), f"{CONFIG_PREFIX}.source-paths")
        ),
        build_type=build_type,
        bundle=bundle,
        icon=icon,
        data_files=tuple(_data_files(project_root, settings.get("data-files", []))),
        collect_packages=tuple(
            _string_list(
                settings.get("collect-packages", []), f"{CONFIG_PREFIX}.collect-packages"
            )
        ),
        hidden_imports=tuple(
            _string_list(settings.get("hidden-imports", []), f"{CONFIG_PREFIX}.hidden-imports")
        ),
    )


def _build_metadata(
    settings: Mapping[str, Any],
    project_name: str,
    version: str,
    internal_name: str,
) -> BuildMetadata:
    return BuildMetadata(
        name=project_name,
        version=version,
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


def resolve_project_path(root: Path, value: str) -> Path:
    """Resolve a configured path against its project root."""
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


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
        raise ConfigurationError(f"{CONFIG_PREFIX}.{key} must be a string")
    value = value.strip()
    if key in {"product-name", "file-description"} and not value:
        raise ConfigurationError(f"{CONFIG_PREFIX}.{key} must be a non-empty string")
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
    path = resolve_project_path(root, value.strip())
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
    key = f"{CONFIG_PREFIX}.data-files"
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
