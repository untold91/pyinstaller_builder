# buildtools-python

`buildtools-python` configures and runs PyInstaller for an existing Python host
application. It does not create or replace the host application's project
metadata, install the host application's dependencies, or replace PyInstaller.

The tool distribution is named `buildtools-python`, its Python import module
is `pyinstaller_builder`, and its console command is `buildtools-python`.
These names are intentionally distinct from the host project's `[project].name`.

## Add BuildTools to an existing project as a Git submodule

### 1. Open the existing host project root

The host application must already have its own `pyproject.toml`. BuildTools
settings are added to that file under `[tool.buildtools]`; do not edit the
submodule's `pyproject.toml`, which is only used to package the tool.

### 2. Add the submodule

```bash
git submodule add <repository-url> tools/pyinstaller_builder
git submodule update --init --recursive
```

Replace `<repository-url>` with the tool repository URL. Adjust
`tools/pyinstaller_builder` if your team uses a different submodule path.

### 3. Install into the host project's active environment

Activate the host project's virtual environment first, then install the tool
from its submodule:

```bash
python -m pip install -e ./tools/pyinstaller_builder
```

This installs the tool and its declared runtime dependencies (including
PyInstaller 6.x) into the selected environment. Use the same interpreter for
subsequent commands.

### 4. Confirm installation and help

```bash
python -m pyinstaller_builder --help
buildtools-python --help
```

The module command is available from Python 3.10+; the console command is
registered by the editable installation.

For a one-off direct invocation from a source checkout, the compatibility
launcher is also available:

```bash
python tools/pyinstaller_builder/build_script.py build --project-dir .
```

It adds that checkout's `src` directory to the import path and then runs the
same CLI; it still resolves configuration from the host project directory.

### 5. Initialize the host project

Run from the host root, or pass its path explicitly:

```bash
buildtools-python init --project-dir .
```

The interactive initializer discovers likely entry points, source directories,
icons, and the project version, then asks you to confirm a summary before it
writes anything. It preserves other TOML metadata and comments. If BuildTools
settings already exist, it offers keep, selective update, or replacement.
After successful validation and save, it writes
`[tool.buildtools].initialized = true`. Cancelling or declining leaves the
file unchanged.

### 6. Review `[tool.buildtools]`

Here is a complete example. Paths are resolved relative to the host root:

```toml
[tool.buildtools]
initialized = true
entry-point = "src/espress_view/__main__.py"
source-paths = ["src"]
build-type = "release"
bundle = "onefile"
icon = "assets/icons/app.ico"
collect-packages = ["esptool"]
hidden-imports = ["esptool.__main__"]

[[tool.buildtools.data-files]]
source = "assets"
target = "assets"
```

`initialized` must be the boolean `true`, not a string. `entry-point` is
required and must name an existing file. `source-paths` defaults to `[]` and
must contain existing directories. `build-type` defaults to `"release"` and
accepts `"release"` or `"debug"`; `bundle` defaults to `"onefile"` and accepts
`"onefile"` or `"onedir"`. `icon` is optional but must exist if set.
`collect-packages` and `hidden-imports` are optional arrays of non-empty
strings. Each repeated `data-files` table requires an existing `source` file or
directory and accepts an optional relative `target` (default `"."`).

The build version defaults to the host's `[project].version`. Set
`[tool.buildtools].version` only to deliberately override it. If project
version is missing or dynamic, set an explicit BuildTools version during init.
Optional metadata keys are `executable-name`, `internal-name`, `company-name`,
`author`, `product-name`, and `file-description`. The default executable name
is `<internal-name>_v<version>_<interpreter-architecture>`.

### 7. Build the application

```bash
buildtools-python build --project-dir .
```

Relative paths resolve from the host root, regardless of the tool installation
location. The command runs `sys.executable -m PyInstaller` with argument
arrays, preserving spaces in paths. Build output, work files, and generated
specification files are placed in the host project's `dist/` and `build/`
directories. Windows builds additionally generate version resources under
`build/`; those metadata options are Windows-specific. PyInstaller targets the
active interpreter's platform and architecture and does not cross-compile.

PyInstaller 6.x accepts `--add-data` values in `SOURCE:DEST` form on the
supported platforms; the tool uses that documented syntax.

### 8. Clean generated artifacts

```bash
buildtools-python clean --project-dir .
buildtools-python clean --project-dir . --dry-run
```

Cleanup is independent of `initialized` and build-input validity. It only
targets the conventional host-root `build/` and `dist/` directories, refuses
symlinks and non-directory targets, skips missing directories, and reports
removed/skipped targets. `--dry-run` lists exact candidates without deleting.

### 9. Automatic initialization before build

If `build` finds a missing, false, or invalid BuildTools configuration in an
interactive terminal, it explains the problem and asks whether to initialize
or update it. On **Y**, it enters the same confirmed setup flow as `init` and
continues the original build exactly once after a successful save. On **N**, it
does not write or build and prints the `buildtools-python init` command to run
later. Cancellation, validation errors, or write failures stop the build. In
non-interactive/CI use, it never prompts; run `init` in advance and ensure
`initialized = true`.

Malformed TOML is never overwritten automatically. Repair the syntax
manually, review the project file, then run `init` again.

### 10. Clone on another machine

Clone the host repository and its submodules together:

```bash
git clone --recurse-submodules <parent-repository-url>
```

For a repository already cloned without submodules:

```bash
git submodule update --init --recursive
```

Then activate the host project's virtual environment and install the
submodule package using step 3's command.

### 11. Troubleshooting

- **Submodule directory is empty:** run `git submodule update --init --recursive`.
- **Command/module not found:** activate the intended virtual environment and
  install `./tools/pyinstaller_builder` with that interpreter's
  `python -m pip`.
- **Wrong project root:** run from a directory under the host project or pass
  `--project-dir PATH`. Discovery walks upward from the current directory,
  chooses the nearest host `pyproject.toml`, and skips this tool's own
  packaging TOML. It does not search unrelated sibling directories.
- **No host TOML found from the submodule:** run the command from the host
  project or pass its root explicitly.
- **Malformed TOML:** repair the host `pyproject.toml` manually before running
  `init`; the tool will not replace malformed input.
- **Invalid entry point or icon:** ensure the configured file exists relative
  to the host root. Source paths must be existing directories.
- **Configuration not initialized:** run `buildtools-python init` and confirm
  the summary; the host TOML must contain `initialized = true`.
- **PyInstaller build failure:** verify the active environment contains
  PyInstaller 6.x and that hidden imports, package collection, data paths,
  and platform-specific assets are valid.

## Tool development

The tool repository's own `pyproject.toml` contains packaging metadata for the
`buildtools-python` distribution. It is not the host application's config.
Python 3.10 or newer and PyInstaller 6.x are the declared compatibility
targets; supported operating systems are Windows, macOS, and Linux, subject
to PyInstaller's platform-specific support and bootloaders.

From the tool repository:

```bash
python -m pip install -e . pytest
python -m pytest -q
python -m build
```
