from __future__ import annotations

from pathlib import Path

import pytest

from pyinstaller_builder.pyinstaller_builder import CleanUtility


def test_clean_only_removes_build_and_dist_and_ignores_missing_inputs(tmp_path: Path) -> None:
    for name in ("build", "dist"):
        output = tmp_path / name
        output.mkdir()
        (output / "artifact.txt").write_text("generated", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text("not parsed for clean", encoding="utf-8")

    result = CleanUtility.clean(tmp_path)
    assert {path.name for path in result.removed} == {"build", "dist"}
    assert result.skipped == ()
    assert not (tmp_path / "build").exists()
    assert not (tmp_path / "dist").exists()
    assert (tmp_path / "src").is_dir()


def test_dry_run_reports_without_deleting(tmp_path: Path) -> None:
    (tmp_path / "build").mkdir()
    result = CleanUtility.clean(tmp_path, dry_run=True)
    assert result.would_remove == (tmp_path / "build",)
    assert result.skipped == (tmp_path / "dist",)
    assert (tmp_path / "build").is_dir()


def test_clean_refuses_symlinked_output(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    try:
        (tmp_path / "build").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    try:
        with pytest.raises(OSError, match="symlinked output"):
            CleanUtility.clean(tmp_path)
        assert (outside / "keep.txt").is_file()
    finally:
        (tmp_path / "build").unlink(missing_ok=True)
        (outside / "keep.txt").unlink(missing_ok=True)
        outside.rmdir()


def test_clean_refuses_file_at_output_path(tmp_path: Path) -> None:
    (tmp_path / "dist").write_text("keep", encoding="utf-8")
    with pytest.raises(OSError, match="non-directory"):
        CleanUtility.clean(tmp_path)
    assert (tmp_path / "dist").is_file()


def test_clean_refuses_home_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(OSError, match="unsafe project root"):
        CleanUtility.clean(tmp_path)


def test_clean_refuses_symlink_target_even_when_link_creation_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "build"
    target.mkdir()
    original = Path.is_symlink

    def is_symlink(path: Path) -> bool:
        return True if path == target else original(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    with pytest.raises(OSError, match="symlinked output"):
        CleanUtility.clean(tmp_path)
    assert target.is_dir()
