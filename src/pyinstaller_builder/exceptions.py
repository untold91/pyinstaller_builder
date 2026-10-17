"""Exceptions exposed by buildtools-python."""


class BuildToolsError(Exception):
    """Base class for expected user-facing errors."""


class ConfigurationError(BuildToolsError):
    """Raised when pyproject.toml contains missing or invalid settings."""


class UninitializedConfigurationError(ConfigurationError):
    """Raised when the host project has no confirmed BuildTools configuration."""


class ProjectFileError(BuildToolsError):
    """Raised when a project TOML file cannot be safely read or parsed."""


class InitializationCancelled(BuildToolsError):
    """Raised when an interactive init flow is cancelled."""
