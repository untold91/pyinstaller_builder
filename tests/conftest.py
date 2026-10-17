from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "src" / "example app").mkdir(parents=True)
    (tmp_path / "src" / "example app" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "data.txt").write_text("data\n", encoding="utf-8")
    (tmp_path / "app.ico").write_bytes(b"icon")
    (tmp_path / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "example-app"
version = "1.2.3"
requires-python = ">=3.10"

[tool.custom]
preserved = true

[tool.pyinstaller_builder]
initialized = true
entry-point = "src/example app/main.py"
source-paths = ["src"]
build-type = "release"
bundle = "onefile"
icon = "app.ico"
collect-packages = ["example_plugin"]
hidden-imports = ["example_plugin.backend"]

[[tool.pyinstaller_builder.data-files]]
source = "assets"
target = "assets"
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path
