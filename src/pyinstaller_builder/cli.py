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
        project_root = resolve_project_root(args.project_dir)
        if args.command == "init":
            if not can_prompt:
                raise PyInstallerBuilderError(
                    "init requires an interactive terminal. Run "
                    "'pyinstaller_builder init --project-dir PATH' from a terminal."
                )
            changed = initialize(project_root, input_fn=ask, output_fn=show)
            if not changed:
                show("Existing configuration was left unchanged.")
            return 0
        if args.command == "clean":
            result = CleanUtility.clean(project_root, dry_run=args.dry_run)
            for target in result.removed:
                show(f"Removed {target}")
            for target in result.would_remove:
                show(f"Would remove {target}")
            for target in result.skipped:
                show(f"Skipped missing output: {target}")
            return 0

        try:
            config = BuildConfig.load(project_root)
        except ConfigurationError as exc:
            if not can_prompt:
                raise ConfigurationError(
                    f"{exc}\nRun 'pyinstaller_builder init --project-dir {project_root}' "
                    "in an interactive terminal."
                ) from exc
            show(f"pyinstaller_builder configuration needs initialization or repair: {exc}")
            if _ask_yes_no(ask, show, "Initialize or update it now? [Y/N]: ") is False:
                show(
                    f"Build cancelled. You can initialize later with: "
                    f"pyinstaller_builder init --project-dir {project_root}"
                )
                return 2
            changed = initialize(project_root, input_fn=ask, output_fn=show)
            if not changed:
                raise InitializationCancelled(
                    "Initialization did not make a validated configuration; build cancelled."
                ) from exc
            config = BuildConfig.load(project_root)
        PyInstallerBuilder(config).build()
        show(f"Build succeeded; output is in {project_root / 'dist'}")
        return 0
    except InitializationCancelled as exc:
        print(str(exc), file=sys.stderr)
        return 130
    except PyInstallerBuilderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"ERROR: Required file or executable was not found: {exc}", file=sys.stderr)
        return 1
    except PermissionError as exc:
        print(f"ERROR: Permission denied: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: Filesystem or process error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: PyInstaller failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1
    except KeyboardInterrupt:
        print("Operation interrupted by user", file=sys.stderr)
        return 130


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
