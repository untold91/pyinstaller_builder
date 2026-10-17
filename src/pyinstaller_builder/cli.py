"""Command-line interface for pyinstaller_builder."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pyinstaller_builder.config import BuildConfig, CONFIG_PREFIX
from pyinstaller_builder.exceptions import (
    ConfigurationError,
    InitializationCancelled,
    PyInstallerBuilderError,
)
from pyinstaller_builder.init import initialize
from pyinstaller_builder.project import resolve_project_root
from pyinstaller_builder.pyinstaller_builder import CleanUtility, PyInstallerBuilder


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line parser with host-project discovery guidance."""
    parser = argparse.ArgumentParser(
        prog="pyinstaller_builder",
        description=(
            "Configure and run PyInstaller builds for a host application. "
            "Settings are stored in the host project's pyproject.toml under "
            f"{CONFIG_PREFIX}; they are separate from this tool's packaging TOML."
        ),
        epilog=(
            "By default, discovery starts in the current directory and selects the "
            "nearest host pyproject.toml, skipping this tool's own checkout. Use "
            "--project-dir PATH to select the host root explicitly. Build requires "
            f"{CONFIG_PREFIX}.initialized = true."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command, description in (
        ("init", "Initialize or update pyinstaller_builder settings in the host project"),
        ("build", "Build the configured host application"),
        ("clean", "Remove generated build and dist folders"),
    ):
        subparser = commands.add_parser(command, help=description, description=description)
        subparser.add_argument(
            "--project-dir",
            type=Path,
            default=None,
            help="Host project root (default: discover from the current directory)",
        )
        if command == "clean":
            subparser.add_argument(
                "--dry-run", action="store_true", help="Show output folders without removing them"
            )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
    interactive: bool | None = None,
) -> int:
    """Run a command against a resolved host root and return its exit code."""
    args = create_parser().parse_args(argv)
    ask = input_fn or input
    show = output_fn or print
    can_prompt = sys.stdin.isatty() if interactive is None else interactive
    try:
        return _run_command(args, ask, show, can_prompt)
    except (
        InitializationCancelled,
        PyInstallerBuilderError,
        FileNotFoundError,
        PermissionError,
        OSError,
        subprocess.CalledProcessError,
        KeyboardInterrupt,
    ) as exc:
        return _report_command_error(exc)


def _run_command(
    args: argparse.Namespace,
    ask: Callable[[str], str],
    show: Callable[[str], None],
    can_prompt: bool,
) -> int:
    project_root = resolve_project_root(args.project_dir)
    if args.command == "init":
        return _run_init(project_root, ask, show, can_prompt)
    if args.command == "clean":
        return _run_clean(project_root, args.dry_run, show)
    return _run_build(project_root, ask, show, can_prompt)


def _run_init(
    project_root: Path,
    ask: Callable[[str], str],
    show: Callable[[str], None],
    can_prompt: bool,
) -> int:
    if not can_prompt:
        raise PyInstallerBuilderError(
            "init requires an interactive terminal. Run "
            "'pyinstaller_builder init --project-dir PATH' from a terminal."
        )
    if not initialize(project_root, input_fn=ask, output_fn=show):
        show("Existing configuration was left unchanged.")
    return 0


def _run_clean(project_root: Path, dry_run: bool, show: Callable[[str], None]) -> int:
    result = CleanUtility.clean(project_root, dry_run=dry_run)
    for message in result.messages():
        show(message)
    return 0


def _run_build(
    project_root: Path,
    ask: Callable[[str], str],
    show: Callable[[str], None],
    can_prompt: bool,
) -> int:
    config = _load_build_config(project_root, ask, show, can_prompt)
    if config is None:
        return 2
    PyInstallerBuilder(config).build()
    show(f"Build succeeded; output is in {project_root / 'dist'}")
    return 0


def _load_build_config(
    project_root: Path,
    ask: Callable[[str], str],
    show: Callable[[str], None],
    can_prompt: bool,
) -> BuildConfig | None:
    try:
        return BuildConfig.load(project_root)
    except ConfigurationError as exc:
        if not can_prompt:
            raise ConfigurationError(
                f"{exc}\nRun 'pyinstaller_builder init --project-dir {project_root}' "
                "in an interactive terminal."
            ) from exc
        show(f"pyinstaller_builder configuration needs initialization or repair: {exc}")
        if not _ask_yes_no(ask, show, "Initialize or update it now? [Y/N]: "):
            show(
                f"Build cancelled. You can initialize later with: "
                f"pyinstaller_builder init --project-dir {project_root}"
            )
            return None
        if not initialize(project_root, input_fn=ask, output_fn=show):
            raise InitializationCancelled(
                "Initialization did not make a validated configuration; build cancelled."
            ) from exc
        return BuildConfig.load(project_root)


def _report_command_error(error: BaseException) -> int:
    message = "Operation interrupted by user"
    exit_code = 130
    if isinstance(error, InitializationCancelled):
        message = str(error)
    elif isinstance(error, PyInstallerBuilderError):
        message, exit_code = f"ERROR: {error}", 2
    elif isinstance(error, FileNotFoundError):
        message = f"ERROR: Required file or executable was not found: {error}"
        exit_code = 1
    elif isinstance(error, PermissionError):
        message, exit_code = f"ERROR: Permission denied: {error}", 1
    elif isinstance(error, OSError):
        message, exit_code = f"ERROR: Filesystem or process error: {error}", 1
    elif isinstance(error, subprocess.CalledProcessError):
        message = f"ERROR: PyInstaller failed with exit code {error.returncode}"
        exit_code = error.returncode or 1
    print(message, file=sys.stderr)
    return exit_code


def _ask_yes_no(
    ask: Callable[[str], str], show: Callable[[str], None], prompt: str
) -> bool:
    while True:
        try:
            answer = ask(prompt).strip().lower()
        except EOFError as exc:
            raise InitializationCancelled(
                "Initialization prompt ended; build cancelled without changes."
            ) from exc
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        show("Please answer Y or N.")


if __name__ == "__main__":
    raise SystemExit(main())
