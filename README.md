# pyinstaller_builder

`pyinstaller_builder` configures and runs PyInstaller for an existing Python
host application. It does not create the host project's metadata, manage its
application dependencies, replace PyInstaller, or cross-compile binaries.

The package import, distribution identity, and console command are all named
`pyinstaller_builder`. Package indexes may normalize underscores and hyphens
in distribution names; the Python import and command remain
`pyinstaller_builder`.

## Add `pyinstaller_builder` to an existing project as a Git submodule

### 1. Open the existing host project

Start from the host application's root. The host must already have a
`pyproject.toml`. That file contains the host's
`[tool.pyinstaller_builder]` settings. The submodule has its own
`pyproject.toml` for packaging the tool; do not configure the host build in
that file.

### 2. Add the Git submodule

```bash
git submodule add <repository-url> tools/pyinstaller_builder
git submodule update --init --recursive
```

Replace `<repository-url>` with the actual repository URL. Adjust
`tools/pyinstaller_builder` if your team uses another submodule path.

### 3. Create or activate the host project's virtual environment

Use the host project's existing virtual environment if it has one. Otherwise,
create `.venv` once at the host project root, then activate it before
installing or running the tool:

```powershell
if (-not (Test-Path .venv)) { py -m venv .venv }
.\.venv\Scripts\Activate.ps1
```

```bash
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
```

Reuse that environment for subsequent commands; do not recreate it each time.
If your project uses another environment directory, activate that instead.

### 4. Install the tool into that environment

```bash
python -m pip install -e ./tools/pyinstaller_builder
```

This installs the reusable tool and its dependencies into the active
environment. It does not alter the host application's name, version,
dependencies, or build backend.

### 5. Confirm installation and help

```bash
pyinstaller_builder --help
pyinstaller_builder init --help
pyinstaller_builder build --help
pyinstaller_builder clean --help
```

Module invocation is also supported:

```bash
python -m pyinstaller_builder --help
python -m pyinstaller_builder init
python -m pyinstaller_builder build
python -m pyinstaller_builder clean
```

The distribution is installed as `pyinstaller_builder`; its import module and
console command use the same spelling.

### 6. Initialize the host project

If the host project already has a `pyproject.toml`, run initialization from the
project root or pass the directory explicitly:

```bash
pyinstaller_builder init --project-dir .
```

If the project does not yet have a `pyproject.toml`, `pyinstaller_builder init`
works from that directory as well. It creates a minimal project file with the
folder name and version `0.1.0`, then validates and writes the required
`[tool.pyinstaller_builder]` configuration. You can also point at an arbitrary
host root explicitly:

```bash
pyinstaller_builder init --project-dir "C:/work/host app"
```

The initializer discovers likely entry points, source directories, icons, and
the host `[project].version`. It validates settings, previews the proposed
configuration, and asks for confirmation before writing. Existing canonical
settings can be kept, selectively updated, or replaced. Once required settings
validate and save successfully, it writes `initialized = true`.

If you run `build` before initialization in an interactive terminal, the tool
asks whether to initialize or repair the settings. Answer **Y** to enter the
same confirmed setup flow; a successful save resumes that build once. Answer
**N** to cancel without modifying the file or building. Cancellation and
failures also stop the build. Non-interactive use never waits for input; run
`init` before building in CI.

When initialization is declined or fails, the existing `pyproject.toml` remains
unchanged, and the build exits without running PyInstaller.

### 7. Review the host TOML

This is a complete example using the canonical namespace:

```toml
[tool.pyinstaller_builder]
initialized = true
entry-point = "src/my_application/__main__.py"
source-paths = ["src"]
build-type = "release"
bundle = "onefile"
icon = "assets/app.ico"
collect-packages = []
hidden-imports = []

[[tool.pyinstaller_builder.data-files]]
source = "assets"
target = "assets"
```

`initialized` must be a TOML boolean. `entry-point` is required and must be
an existing file. `source-paths` defaults to `[]` and must contain existing
directories. `build-type` defaults to `"release"` and accepts `"release"` or
`"debug"`; `bundle` defaults to `"onefile"` and accepts `"onefile"` or
`"onedir"`. `icon` is optional but must exist when configured.
`collect-packages` and `hidden-imports` default to empty arrays. Each
`data-files` table requires an existing file or directory as `source`; its
relative bundle `target` defaults to `"."`.

The host project's `[project].version` is the source of truth for the build
version. If the host version is absent or dynamic, initialization fills it with
`0.1.0` and keeps the tool config free of duplicate version values. The
package derives `internal-name` from `[project].name` and `file-description`
from `[project].description` at runtime. Optional tool settings are
`executable-name`, `company-name`, `author`, and `product-name`; the default
executable name is `<internal-name>_v<version>_<interpreter-architecture>`.

If an older configuration still contains `version` or `file-description` under
`[tool.pyinstaller_builder]`, the loader treats those as migration fallbacks
only when the matching `[project]` field is absent. It prefers valid
`[project]` metadata and writes no duplicate metadata keys back into the tool
section.

A minimal project created by `pyinstaller_builder init` looks like this:

```text
my-host-app/
├── pyproject.toml
├── src/
│   └── my_host_app/
│       └── __main__.py
├── build/
├── dist/
└── assets/
```

`pyinstaller_builder` writes the config into the host app's `pyproject.toml`
and keeps unrelated TOML sections intact. Any existing `[project]` metadata is
preserved while the tool-specific settings are added or updated.

### 8. Build the application

```bash
pyinstaller_builder build --project-dir .
```

All configured relative paths are resolved from the host project root. The
tool invokes `sys.executable -m PyInstaller` with a list of arguments, so
spaces in paths are preserved. PyInstaller writes distribution output to
`dist/`; build work files and generated specification files are stored in
`build/`. On Windows, version metadata is generated under `build/` and passed
to PyInstaller. PyInstaller builds for the active interpreter's platform and
architecture. Windows, macOS, and Linux are supported subject to PyInstaller's
platform support and compatible bootloader.

The tool targets PyInstaller 6.x. Its `--add-data` argument uses the documented
`SOURCE:DEST` syntax.

### 9. Clean generated artifacts

```bash
pyinstaller_builder clean --project-dir .
pyinstaller_builder clean --project-dir . --dry-run
```

Cleanup is available even when build settings are absent or invalid. It only
considers the host-root `build/` and `dist/` directories, refuses symlinks and
non-directory paths, skips missing outputs, and reports removed or skipped
targets. It will not accept arbitrary cleanup paths. `--dry-run` lists the
exact directories that would be removed.

### 10. Migrate older configuration

Earlier releases used `[tool.buildtools]`. That namespace is supported only
for explicit, one-time migration; the active parser and initializer use
`[tool.pyinstaller_builder]`.

When only the old table exists, `init` offers to copy its settings—including
repeated data-file entries—to the canonical table. It previews and validates
the result, then requires confirmation before removing the old table. Declining
leaves the file unchanged. If both tables exist, the tool shows both and
requires you to explicitly choose which table to keep or cancel; it never
merges or silently prefers conflicting values.

### 11. Clone the parent repository on another machine

Clone the host project and its submodules:

```bash
git clone --recurse-submodules <parent-repository-url>
```

For an existing clone without submodules:

```bash
git submodule update --init --recursive
```

Activate the host project's virtual environment, install the submodule with
step 4, then verify the command with `pyinstaller_builder --help`.

### 12. Troubleshooting

- **Submodule is missing or empty:** run `git submodule update --init --recursive`.
- **Import or command is unavailable:** activate the intended environment and
  run `python -m pip install -e ./tools/pyinstaller_builder` with that
  environment's Python.
- **Wrong host root:** run from the host root or pass `--project-dir PATH`.
  Discovery starts at the current directory, walks upward, and skips the
  tool's own packaging project; it does not search unrelated siblings.
- **Tool TOML appears to be used:** pass the host directory explicitly with
  `--project-dir`; the tool's packaging TOML is not host configuration.
- **Legacy `[tool.buildtools]` found:** run `pyinstaller_builder init` and
  review the explicit migration before confirming.
- **Both configuration tables exist:** choose which table to retain in the
  conflict-resolution prompt or cancel and resolve the TOML manually.
- **Malformed TOML:** repair the host `pyproject.toml` manually before
  running `init`; malformed files are not overwritten.
- **Entry point or icon is invalid:** configure an existing file relative to
  the host root. Source paths must be existing directories.
- **Project is not initialized:** run `pyinstaller_builder init` and confirm
  the validated settings.
- **PyInstaller is missing or the build fails:** confirm the active
  environment has the declared PyInstaller 6.x dependency, then inspect
  PyInstaller's diagnostics and configured imports, data files, and assets.

## Tool development

The tool repository's `pyproject.toml` packages `pyinstaller_builder`; a host
project's `pyproject.toml` configures the application build. Python 3.10 or
newer is the declared minimum. Test/build verification is performed on the
development environment; the tool targets Windows, macOS, and Linux subject
to PyInstaller's platform-specific support. Reuse an existing project
environment, or create and activate `.venv` once:

```powershell
if (-not (Test-Path .venv)) { py -m venv .venv }
.\.venv\Scripts\Activate.ps1
```

```bash
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
```

Install development tools into that active environment, then reuse it for
future runs:

```text
python -m pip install -e . pytest build pylint
python -m pytest -q
python -m build
python -m pylint src tests
```
