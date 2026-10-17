"""Interactive, formatting-preserving initialization of pyinstaller_builder settings."""

from __future__ import annotations

import copy
import os
import stat
import tempfile
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from pyinstaller_builder.config import (
    BUILD_TYPES,
    BUNDLE_MODES,
    BuildConfig,
    CONFIG_TABLE,
    LEGACY_CONFIG_TABLE,
    is_valid_name,
    is_valid_version,
    normalize_data_target,
    resolve_project_path,
)
from pyinstaller_builder.exceptions import (
    ConfigurationError,
    InitializationCancelled,
    ProjectFileError,
    PyInstallerBuilderError,
)

PROMPT_KEYS = (
    "entry-point",
    "source-paths",
    "build-type",
    "bundle",
    "icon",
    "collect-packages",
    "hidden-imports",
    "data-files",
    "version",
    "executable-name",
    "internal-name",
    "company-name",
    "author",
    "product-name",
    "file-description",
)


@dataclass(frozen=True)
class _InitContext:
    root: Path
    path: Path
    document: MutableMapping[str, Any]
    ask: Callable[[str], str]
    show: Callable[[str], None]


def initialize(
    project_root: Path,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
) -> bool:
    """Interactively add or update [tool.pyinstaller_builder]."""
    ask = input_fn or input
    show = output_fn or print
    root = project_root.resolve()
    path = root / "pyproject.toml"
    if not path.is_file():
        raise ConfigurationError(
            f"No pyproject.toml found in {root}. Initialize the Python project first, "
            "then run 'pyinstaller_builder init'."
        )
    try:
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectFileError(f"Could not read {path}: {exc}") from exc
    except ParseError as exc:
        raise ProjectFileError(
            f"Invalid TOML in {path}: {exc}. Repair it manually before running init."
        ) from exc

    context = _InitContext(root, path, document, ask, show)
    try:
        return _initialize_settings(context)
    except (EOFError, KeyboardInterrupt) as exc:
        raise InitializationCancelled(
            "Initialization cancelled; pyproject.toml was not changed."
        ) from exc


def _initialize_settings(context: _InitContext) -> bool:
    legacy = _table_settings(context.document, LEGACY_CONFIG_TABLE)
    existing = _existing_settings(context.document)
    if legacy is not None and existing is not None:
        return _resolve_table_conflict(context, legacy, existing)
    if legacy is not None:
        return _migrate_legacy(context, legacy)
    settings = _choose_settings(context, existing)
    if settings is None:
        return False
    return _confirm_and_write(context, settings)


def _choose_settings(
    context: _InitContext, existing: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if existing is None:
        return _new_settings(context)
    context.show("Existing [tool.pyinstaller_builder] configuration:")
    for key, value in existing.items():
        context.show(f"  {key} = {value!s}")
    action = _ask_choice(
        context.ask,
        context.show,
        "Choose: [k]eep unchanged, [u]pdate selected settings, [r]eplace: ",
        ("k", "u", "r"),
    )
    if action == "k":
        settings = dict(existing.items())
        try:
            _validate_preview(context.document, settings, context.root)
        except ConfigurationError as exc:
            context.show(f"Cannot keep invalid configuration: {exc}")
            action = _ask_choice(
                context.ask,
                context.show,
                "Choose: [u]pdate selected settings or [r]eplace: ",
                ("u", "r"),
            )
        else:
            return None
    if action == "u":
        keys = _ask_update_keys(context.ask, context.show)
        if not keys:
            return None
        settings = dict(existing.items())
        _prompt_settings(settings, keys, context)
        return settings
    return _new_settings(context)


def _confirm_and_write(context: _InitContext, settings: dict[str, Any]) -> bool:
    _ensure_version(settings, context.document, context.ask, context.show)
    settings["initialized"] = True
    _validate_preview(context.document, settings, context.root)
    context.show("Proposed [tool.pyinstaller_builder] configuration:")
    for key, value in settings.items():
        context.show(f"  {key} = {value!r}")
    if _ask_choice(
        context.ask, context.show, "Write these settings? [y/N]: ", ("y", "n")
    ) != "y":
        raise InitializationCancelled("Initialization cancelled; pyproject.toml was not changed.")
    _write_settings(context.document, settings)
    _atomic_write(context.path, tomlkit.dumps(context.document))
    context.show(f"Added pyinstaller_builder settings to {context.path}")
    return True


def _new_settings(
    context: _InitContext,
) -> dict[str, Any]:
    root, ask, show = context.root, context.ask, context.show
    settings: dict[str, Any] = {
        "entry-point": _prompt_entry_point(root, ask, show),
        "source-paths": _prompt_source_paths(root, ask, show),
        "build-type": _prompt_choice(ask, show, "Build type", "release", BUILD_TYPES),
        "bundle": _prompt_choice(ask, show, "Bundle mode", "onefile", BUNDLE_MODES),
        "collect-packages": [],
        "hidden-imports": [],
        "data-files": [],
    }
    icon = _prompt_optional_file("Icon path", _discover_icons(root), context)
    if icon:
        settings["icon"] = icon
    return settings


def _prompt_settings(
    settings: dict[str, Any],
    keys: tuple[str, ...],
    context: _InitContext,
) -> None:
    handlers: dict[str, Callable[[], Any]] = {
        "entry-point": lambda: _prompt_entry_point(context.root, context.ask, context.show),
        "source-paths": lambda: _prompt_source_paths(context.root, context.ask, context.show),
        "build-type": lambda: _prompt_choice(
            context.ask,
            context.show,
            "Build type",
            str(settings.get("build-type", "release")),
            BUILD_TYPES,
        ),
        "bundle": lambda: _prompt_choice(
            context.ask,
            context.show,
            "Bundle mode",
            str(settings.get("bundle", "onefile")),
            BUNDLE_MODES,
        ),
        "icon": lambda: _prompt_icon(settings, context),
        "data-files": lambda: _prompt_data_files(
            context.root, context.ask, context.show, settings.get("data-files", [])
        ),
        "version": lambda: _prompt_configured_version(settings, context),
        "executable-name": lambda: _prompt_name(
            context.ask, context.show, "executable-name", settings.get("executable-name", "")
        ),
        "internal-name": lambda: _prompt_name(
            context.ask, context.show, "internal-name", settings.get("internal-name", "")
        ),
        "product-name": lambda: _prompt_nonempty_text(
            context.ask, context.show, "product-name", settings.get("product-name", "")
        ),
        "file-description": lambda: _prompt_nonempty_text(
            context.ask, context.show, "file-description", settings.get("file-description", "")
        ),
        "company-name": lambda: _prompt_optional_text(settings, "company-name", context),
        "author": lambda: _prompt_optional_text(settings, "author", context),
    }
    for key in ("collect-packages", "hidden-imports"):
        handlers[key] = lambda key=key: _prompt_string_list(
            context.ask, key, settings.get(key, [])
        )
    for key in keys:
        value = handlers[key]()
        if value is None or (key == "icon" and not value):
            settings.pop(key, None)
        else:
            settings[key] = value


def _prompt_icon(settings: Mapping[str, Any], context: _InitContext) -> str:
    return _prompt_optional_file(
        "Icon path",
        _discover_icons(context.root),
        context,
        str(settings.get("icon", "")),
    )


def _prompt_configured_version(settings: Mapping[str, Any], context: _InitContext) -> str:
    project = context.document.get("project")
    project_version = project.get("version") if isinstance(project, Mapping) else ""
    return _prompt_version(
        context.ask, context.show, settings.get("version", project_version)
    )


def _prompt_optional_text(
    settings: dict[str, Any], key: str, context: _InitContext
) -> Any:
    current = settings.get(key, "")
    answer = context.ask(f"{key} [{current}]: ").strip()
    return answer or (current if key in settings else None)


def _ensure_version(
    settings: dict[str, Any],
    document: Mapping[str, Any],
    ask: Callable[[str], str],
    show: Callable[[str], None],
) -> None:
    project = document.get("project")
    project_version = project.get("version") if isinstance(project, Mapping) else None
    configured_version = settings.get("version")
    if (isinstance(configured_version, str) and configured_version.strip()) or (
        isinstance(project_version, str) and project_version.strip()
    ):
        return
    show("[project].version is absent or dynamic; an explicit pyinstaller_builder version is needed.")
    while True:
        value = ask("[tool.pyinstaller_builder].version: ").strip()
        if is_valid_version(value):
            settings["version"] = value
            return
        show("Enter a numeric version such as 1.2.3.")


def _prompt_entry_point(
    root: Path, ask: Callable[[str], str], show: Callable[[str], None]
) -> str:
    candidates = _discover_entry_points(root)
    if len(candidates) > 1:
        show("Entry point candidates:")
        for index, candidate in enumerate(candidates, start=1):
            show(f"  {index}. {candidate}")
        while True:
            answer = ask("Select a candidate number or enter a path: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(candidates):
                return candidates[int(answer) - 1]
            if _valid_path(root, answer, "file"):
                return answer
            show("Choose a listed number or an existing file path.")
    default = candidates[0] if candidates else ""
    if default:
        show(f"Discovered entry point: {default}")
    while True:
        answer = ask(f"Entry point [{default}]: ").strip() or default
        if _valid_path(root, answer, "file"):
            return answer
        show("Enter a path to an existing file.")


def _prompt_source_paths(
    root: Path, ask: Callable[[str], str], show: Callable[[str], None]
) -> list[str]:
    defaults = ["src"] if (root / "src").is_dir() else []
    rendered = ", ".join(defaults)
    while True:
        answer = ask(f"Source directories, comma-separated [{rendered}]: ").strip()
        values = [item.strip() for item in answer.split(",") if item.strip()] if answer else defaults
        if all(_valid_path(root, item, "directory") for item in values):
            return values
        show("Every source path must be an existing directory.")


def _prompt_optional_file(
    label: str,
    candidates: list[str],
    context: _InitContext,
    current: str = "",
) -> str:
    root, ask, show = context.root, context.ask, context.show
    default = current or (candidates[0] if len(candidates) == 1 else "")
    if len(candidates) > 1:
        show(f"Discovered {label.lower()} candidates: {', '.join(candidates)}")
    while True:
        answer = ask(f"{label} (blank for none) [{default}]: ").strip() or default
        if not answer or _valid_path(root, answer, "file"):
            return answer
        show("Enter a path to an existing file, or leave it blank.")


def _prompt_choice(
    ask: Callable[[str], str],
    show: Callable[[str], None],
    label: str,
    default: str,
    options: tuple[str, ...],
) -> str:
    while True:
        answer = ask(f"{label} {options} [{default}]: ").strip() or default
        if answer in options:
            return answer
        show(f"Choose one of: {', '.join(options)}.")


def _prompt_string_list(
    ask: Callable[[str], str], label: str, current: Any
) -> list[str]:
    default = ", ".join(current) if isinstance(current, list) else ""
    answer = ask(f"{label}, comma-separated [{default}]: ").strip()
    values = [item.strip() for item in answer.split(",") if item.strip()] if answer else (
        current if isinstance(current, list) else []
    )
    return values


def _prompt_data_files(
    root: Path, ask: Callable[[str], str], show: Callable[[str], None], current: Any
) -> list[dict[str, str]]:
    show_current = ", ".join(
        f"{item.get('source')}={item.get('target', '.')}"
        for item in current
        if isinstance(item, Mapping)
    ) if isinstance(current, list) else ""
    while True:
        answer = ask(
            f"Data files as source=target pairs separated by commas [{show_current}]: "
        ).strip()
        if not answer:
            return current if isinstance(current, list) else []
        result: list[dict[str, str]] = []
        for pair in answer.split(","):
            source, separator, target = pair.partition("=")
            if (
                not separator
                or not source.strip()
                or not target.strip()
                or not _valid_path(root, source.strip(), "any")
            ):
                break
            try:
                normalized_target = normalize_data_target(target, "data-file target")
            except ConfigurationError:
                break
            result.append({"source": source.strip(), "target": normalized_target})
        else:
            return result
        show("Enter each existing source and a safe relative target as source=target.")


def _prompt_version(
    ask: Callable[[str], str], show: Callable[[str], None], default: Any
) -> str:
    if not isinstance(default, str):
        default = ""
    while True:
        value = ask(f"[tool.pyinstaller_builder].version [{default}]: ").strip() or default
        if is_valid_version(value):
            return value
        show("Enter a numeric version such as 1.2.3.")


def _prompt_name(
    ask: Callable[[str], str],
    show: Callable[[str], None],
    key: str,
    current: Any,
) -> str:
    default = current if isinstance(current, str) else ""
    while True:
        value = ask(f"{key} [{default}]: ").strip() or default
        if value and is_valid_name(value):
            return value
        show("Enter a non-empty name without path separators or reserved filename characters.")


def _prompt_nonempty_text(
    ask: Callable[[str], str],
    show: Callable[[str], None],
    key: str,
    current: Any,
) -> str:
    default = current if isinstance(current, str) else ""
    while True:
        value = ask(f"{key} [{default}]: ").strip() or default
        if value:
            return value
        show("Enter a non-empty value.")


def _discover_entry_points(root: Path) -> list[str]:
    candidates: list[Path] = []
    for pattern in ("src/*/__main__.py", "src/*/main.py", "src/main.py", "main.py", "app.py"):
        candidates.extend(root.glob(pattern))
    return sorted({path.relative_to(root).as_posix() for path in candidates if path.is_file()})


def _discover_icons(root: Path) -> list[str]:
    candidates: set[str] = set()
    for folder in (root / "assets", root / "icons"):
        if folder.is_dir():
            for extension in ("*.ico", "*.icns", "*.png"):
                candidates.update(path.relative_to(root).as_posix() for path in folder.rglob(extension))
    for path in (root / "icon.ico", root / "icon.icns", root / "icon.png"):
        if path.is_file():
            candidates.add(path.relative_to(root).as_posix())
    return sorted(candidates)


def _valid_path(root: Path, value: str, expected: str) -> bool:
    if not value.strip():
        return False
    path = resolve_project_path(root, value.strip())
    if expected == "file":
        return path.is_file()
    if expected == "directory":
        return path.is_dir()
    return path.exists()


def _ask_update_keys(
    ask: Callable[[str], str], show: Callable[[str], None]
) -> tuple[str, ...]:
    show(f"Settings: {', '.join(PROMPT_KEYS)}")
    while True:
        answer = ask("Enter setting names separated by commas (or 'all'): ").strip()
        if answer == "all":
            return PROMPT_KEYS
        keys = tuple(dict.fromkeys(item.strip() for item in answer.split(",") if item.strip()))
        if all(key in PROMPT_KEYS for key in keys):
            return keys
        show("Use only the listed setting names.")


def _ask_choice(
    ask: Callable[[str], str],
    show: Callable[[str], None],
    prompt: str,
    choices: tuple[str, ...],
) -> str:
    while True:
        answer = ask(prompt).strip().lower()
        if answer in choices:
            return answer
        show(f"Choose one of: {', '.join(choices)}.")


def _existing_settings(document: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return _table_settings(document, CONFIG_TABLE)


def _table_settings(document: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    tool = document.get("tool")
    if tool is None:
        return None
    if not isinstance(tool, Mapping):
        raise ConfigurationError("[tool] must be a TOML table")
    settings = tool.get(name)
    if settings is None:
        return None
    if not isinstance(settings, Mapping):
        raise ConfigurationError(f"[tool.{name}] must be a TOML table")
    return settings


def _migrate_legacy(
    context: _InitContext,
    legacy: Mapping[str, Any],
) -> bool:
    document, path, root, ask, show = (
        context.document,
        context.path,
        context.root,
        context.ask,
        context.show,
    )
    show("Found legacy [tool.buildtools] settings.")
    if _ask_choice(
        ask,
        show,
        "Migrate all settings and data-files to [tool.pyinstaller_builder]? [y/N]: ",
        ("y", "n"),
    ) != "y":
        show(
            "No changes made. To migrate manually, copy [tool.buildtools] to "
            "[tool.pyinstaller_builder] in pyproject.toml, then remove the old table."
        )
        return False
    settings = dict(legacy.items())
    if "initialized" in settings and not isinstance(settings["initialized"], bool):
        raise ConfigurationError(
            "[tool.buildtools].initialized must be a boolean before migration"
        )
    settings["initialized"] = True
    _validate_preview_with_legacy(document, settings, root)
    show("Migration summary:")
    for key, value in settings.items():
        show(f"  {key} = {value!s}")
    if _ask_choice(ask, show, "Save this migration? [y/N]: ", ("y", "n")) != "y":
        show("No changes made. The legacy table remains unchanged.")
        return False
    _write_settings(document, settings)
    tool = document["tool"]
    del tool[LEGACY_CONFIG_TABLE]
    _atomic_write(path, tomlkit.dumps(document))
    show("Migrated settings to [tool.pyinstaller_builder].")
    return True


def _resolve_table_conflict(
    context: _InitContext,
    legacy: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    document, root, ask, show = (
        context.document,
        context.root,
        context.ask,
        context.show,
    )
    show("Both [tool.buildtools] and [tool.pyinstaller_builder] exist.")
    show("Legacy settings:")
    for key, value in legacy.items():
        show(f"  {key} = {value!s}")
    show("Canonical settings:")
    for key, value in current.items():
        show(f"  {key} = {value!s}")
    action = _ask_choice(
        ask,
        show,
        "Choose [l]egacy settings, keep [n]ew settings, or [c]ancel: ",
        ("l", "n", "c"),
    )
    if action == "c":
        show("No changes made; both tables are preserved.")
        return False
    selected = dict(legacy.items() if action == "l" else current.items())
    selected["initialized"] = True
    _validate_preview_with_legacy(document, selected, root, selected_table=action)
    show(f"Selected {'legacy' if action == 'l' else 'canonical'} settings:")
    for key, value in selected.items():
        show(f"  {key} = {value!s}")
    if _ask_choice(ask, show, "Save this resolution and remove the other table? [y/N]: ",
                   ("y", "n")) != "y":
        show("No changes made; both tables are preserved.")
        return False
    _write_settings(document, selected)
    tool = document["tool"]
    if action == "l":
        del tool[CONFIG_TABLE]
    else:
        del tool[LEGACY_CONFIG_TABLE]
    _atomic_write(context.path, tomlkit.dumps(document))
    show("Configuration conflict resolved.")
    return True


def _validate_preview_with_legacy(
    document: Mapping[str, Any],
    settings: dict[str, Any],
    root: Path,
    *,
    selected_table: str = "l",
) -> None:
    preview = copy.deepcopy(document)
    tool = preview.get("tool")
    if not isinstance(tool, MutableMapping):
        raise ConfigurationError("[tool] must be a TOML table")
    if selected_table == "l":
        del tool[LEGACY_CONFIG_TABLE]
    else:
        del tool[CONFIG_TABLE]
    _write_settings(preview, settings)
    BuildConfig.from_document(preview, root)


def _validate_preview(
    document: Mapping[str, Any], settings: dict[str, Any], root: Path
) -> None:
    preview = copy.deepcopy(document)
    _write_settings(preview, settings)
    BuildConfig.from_document(preview, root)


def _write_settings(document: MutableMapping[str, Any], settings: Mapping[str, Any]) -> None:
    tool = document.get("tool")
    if tool is None:
        tool = tomlkit.table()
        document["tool"] = tool
    if not isinstance(tool, MutableMapping):
        raise ConfigurationError("[tool] must be a TOML table")
    config_table = tool.get(CONFIG_TABLE)
    if config_table is None:
        config_table = tomlkit.table()
        tool[CONFIG_TABLE] = config_table
    if not isinstance(config_table, MutableMapping):
        raise ConfigurationError("[tool] must be a TOML table")
    for key, value in settings.items():
        if key == "data-files":
            if not isinstance(value, list) or any(
                not isinstance(entry, Mapping) for entry in value
            ):
                raise ConfigurationError(
                    "[tool.pyinstaller_builder].data-files must be an array of tables"
                )
            array = tomlkit.aot()
            for entry in value:
                table = tomlkit.table()
                for entry_key, entry_value in entry.items():
                    table[entry_key] = entry_value
                array.append(table)
            config_table[key] = array
        else:
            config_table[key] = value
    config_table["initialized"] = True


def _atomic_write(path: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    except OSError as exc:
        raise PyInstallerBuilderError(f"Could not safely update {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
