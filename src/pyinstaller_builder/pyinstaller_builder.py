"""PyInstaller argument generation and process execution."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pyinstaller_builder.config import BuildConfig

LOGGER = logging.getLogger("pyinstaller_builder")


class PyInstallerBuilder:
    """Build an application using the active Python interpreter."""

    def __init__(self, config: BuildConfig, platform_name: str | None = None) -> None:
        self.config = config
        self.platform_name = platform_name or sys.platform
        self.metadata_file = config.project_root / "build" / "version_metadata.yaml"
        self.version_info_file = config.project_root / "build" / "version_info.txt"

    def arguments(self) -> list[str]:
        """Return deterministic PyInstaller CLI arguments for this build."""
        config = self.config
        arguments = [
            "--noconfirm",
            f"--{config.bundle}",
            "--windowed" if config.build_type == "release" else "--console",
            "--name",
            config.executable_name,
            "--distpath",
            str(config.project_root / "dist"),
            "--workpath",
            str(config.project_root / "build"),
            "--specpath",
            str(config.project_root / "build"),
        ]
        for source_path in config.source_paths:
            arguments.extend(["--paths", str(source_path)])
        for data_file in config.data_files:
            # PyInstaller 6 uses ':' for the source/destination delimiter on all platforms.
            arguments.extend(["--add-data", f"{data_file.source}:{data_file.target}"])
        for package in config.collect_packages:
            arguments.extend(["--collect-all", package])
        for module in config.hidden_imports:
            arguments.extend(["--hidden-import", module])
        if config.icon is not None:
            arguments.extend(["--icon", str(config.icon)])
        if self.platform_name == "win32":
            arguments.extend(["--version-file", str(self.version_info_file)])
        arguments.append(str(config.entry_point))
        return arguments

    def build(self) -> None:
        """Generate optional Windows metadata and run PyInstaller."""
        if self.platform_name == "win32":
            self._generate_version_info()
        command = [sys.executable, "-m", "PyInstaller", *self.arguments()]
        LOGGER.info("Running PyInstaller")
        subprocess.run(command, check=True, cwd=self.config.project_root)
        LOGGER.info("Build succeeded; output is in %s", self.config.project_root / "dist")

    def _generate_version_info(self) -> None:
        """Create the version resource file used by Windows executables."""
        import yaml
        from pyinstaller_versionfile import create_versionfile_from_input_file
        from pyinstaller_versionfile.exceptions import UsageError, ValidationError

        config = self.config
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] = {
            "Version": config.version,
            "FileDescription": config.file_description,
            "InternalName": config.internal_name,
            "LegalCopyright": _copyright(config.company_name, config.author),
            "OriginalFilename": f"{config.executable_name}.exe",
            "ProductName": config.product_name,
            "Translation": [
                {"langID": 0, "charsetID": 1200},
                {"langID": 1033, "charsetID": 1252},
            ],
        }
        if config.company_name:
            metadata["CompanyName"] = config.company_name
        self.metadata_file.write_text(
            yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8"
        )
        try:
            create_versionfile_from_input_file(
                output_file=str(self.version_info_file),
                input_file=str(self.metadata_file),
            )
        except (UsageError, ValidationError) as exc:
            from pyinstaller_builder.exceptions import BuildToolsError

            raise BuildToolsError(f"Could not generate Windows version metadata: {exc}") from exc


def _copyright(company_name: str, author: str) -> str:
    holder = company_name or author
    if not holder:
        return ""
    return f"Copyright (c) {date.today().year} {holder}. All rights reserved."


class CleanUtility:
    """Remove only the conventional project-local PyInstaller output folders."""

    OUTPUTS = ("build", "dist")

    @classmethod
    def clean(cls, project_root: Path, dry_run: bool = False) -> CleanResult:
        """Remove build/dist, rejecting symlinks and non-directory targets."""
        root = project_root.resolve()
        if root == Path(root.anchor) or root == Path.home().resolve():
            raise OSError(f"Refusing cleanup from an unsafe project root: {root}")
        removed: list[Path] = []
        would_remove: list[Path] = []
        skipped: list[Path] = []
        for name in cls.OUTPUTS:
            target = root / name
            try:
                target.lstat()
            except FileNotFoundError:
                skipped.append(target)
                continue
            if target.is_symlink():
                raise OSError(f"Refusing to clean symlinked output directory: {target}")
            if not target.is_dir():
                raise OSError(f"Refusing to clean non-directory output path: {target}")
            resolved_target = target.resolve()
            if resolved_target != target or resolved_target.parent != root:
                raise OSError(f"Refusing to clean path outside the project root: {target}")
            if dry_run:
                would_remove.append(target)
            else:
                shutil.rmtree(target)
                removed.append(target)
        return CleanResult(tuple(removed), tuple(would_remove), tuple(skipped))


@dataclass(frozen=True)
class CleanResult:
    """Cleanup actions performed, proposed in dry-run mode, or skipped."""

    removed: tuple[Path, ...]
    would_remove: tuple[Path, ...]
    skipped: tuple[Path, ...]
