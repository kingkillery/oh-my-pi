class HarnessError(Exception):
    """Base class for user-facing harness errors."""


class TaskValidationError(HarnessError):
    """Raised when task input cannot be normalized into a safe contract."""


class SafetyError(HarnessError):
    """Raised when a safety policy blocks an action."""


class BackendError(HarnessError):
    """Raised when an agent backend fails."""
