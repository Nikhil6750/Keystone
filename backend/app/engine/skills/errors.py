"""Stage 9C Skill Foundry Typed Exceptions."""


class SkillError(Exception):
    """Base exception for all skill-related errors in Keystone."""


class SkillValidationError(SkillError, ValueError):
    """Raised when a skill or frontmatter fails validation constraints."""


class SkillNotFoundError(SkillError, KeyError):
    """Raised when a requested skill or version is not found in the registry/vault."""


class SkillVersionConflictError(SkillError):
    """Raised when attempting to overwrite an existing immutable skill version."""


class SkillVaultSecurityError(SkillError, PermissionError):
    """Raised when an operation violates Obsidian skill vault boundary constraints."""


class MalformedSkillError(SkillError, ValueError):
    """Raised when a markdown note or metadata is corrupt/unparseable."""


class InvalidSkillTransitionError(SkillError, ValueError):
    """Raised when an invalid lifecycle state transition is requested."""


__all__ = [
    "InvalidSkillTransitionError",
    "MalformedSkillError",
    "SkillError",
    "SkillNotFoundError",
    "SkillValidationError",
    "SkillVaultSecurityError",
    "SkillVersionConflictError",
]
