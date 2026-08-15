"""Stage 9D Software Quality Factory Exception Hierarchy."""


class QualityError(Exception):
    """Base exception for all Software Quality Factory errors."""


class QualityProfileNotFoundError(QualityError):
    """Raised when a requested QualityProfile cannot be found."""


class QualityGateExecutionError(QualityError):
    """Raised when a quality gate executor fails to execute a gate check."""


class UnapprovedQualityCommandError(QualityError):
    """Raised when an unapproved executable or command is requested."""


class QualitySecurityError(QualityError):
    """Raised when an unsafe process, command, or path traversal is detected."""


class QualityPlanCompilationError(QualityError):
    """Raised when quality plan compilation fails."""


__all__ = [
    "QualityError",
    "QualityGateExecutionError",
    "QualityPlanCompilationError",
    "QualityProfileNotFoundError",
    "QualitySecurityError",
    "UnapprovedQualityCommandError",
]
