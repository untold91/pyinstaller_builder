"""Exceptions exposed by pyinstaller_builder."""


class PyInstallerBuilderError(Exception):
    """Base class for expected user-facing errors."""


class ConfigurationError(PyInstallerBuilderError):
    """Raised when pyproject.toml contains missing or invalid settings."""


class UninitializedConfigurationError(ConfigurationError):
    """Raised when the host project has no confirmed pyinstaller_builder configuration."""


class LegacyConfigurationError(ConfigurationError):
    """Raised when only the legacy [tool.buildtools] table is present."""


class ConfigurationConflictError(ConfigurationError):
    """Raised when both legacy and canonical configuration tables exist."""


class ProjectFileError(PyInstallerBuilderError):
    """Raised when a project TOML file cannot be safely read or parsed."""


class InitializationCancelled(PyInstallerBuilderError):
    """Raised when an interactive init flow is cancelled."""
