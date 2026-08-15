"""Tests for `app.adapters.workspace.validate_workspace_root` (Stage 8C.3):
the server-side validation boundary for a real coding agent's execution
directory, normally the user's own currently open VS Code workspace.
"""

import pytest

from app.adapters.workspace import WorkspaceValidationError, validate_workspace_root
from app.engine.orchestration.models import OrchestrationRequest


def test_valid_absolute_existing_directory_is_accepted(tmp_path: object) -> None:
    resolved = validate_workspace_root(str(tmp_path))
    assert resolved == str(tmp_path.resolve())  # type: ignore[union-attr]


def test_relative_path_is_rejected() -> None:
    with pytest.raises(WorkspaceValidationError, match="absolute"):
        validate_workspace_root("relative/path")


def test_blank_is_rejected() -> None:
    with pytest.raises(WorkspaceValidationError, match="blank"):
        validate_workspace_root("   ")


def test_nonexistent_path_is_rejected(tmp_path: object) -> None:
    missing = str(tmp_path / "does-not-exist")  # type: ignore[operator]
    with pytest.raises(WorkspaceValidationError, match="does not exist"):
        validate_workspace_root(missing)


def test_file_path_is_rejected_not_a_directory(tmp_path: object) -> None:
    file_path = tmp_path / "a-file.txt"  # type: ignore[operator]
    file_path.write_text("content")
    with pytest.raises(WorkspaceValidationError, match="not a directory"):
        validate_workspace_root(str(file_path))


def test_excessively_long_path_is_rejected() -> None:
    with pytest.raises(WorkspaceValidationError, match="maximum length"):
        validate_workspace_root("C:\\" + ("a" * 5000))


def test_path_traversal_segments_are_normalized_before_validation(tmp_path: object) -> None:
    """`..` segments are resolved, not treated as opaque path text --
    confirming the eventual check is against the real, final directory."""
    nested = tmp_path / "child"  # type: ignore[operator]
    nested.mkdir()
    traversal_path = str(nested / ".." / "child")
    resolved = validate_workspace_root(traversal_path)
    assert resolved == str(nested.resolve())


# --- OrchestrationRequest.workspace_root: never derived from goal text ------


def test_orchestration_request_rejects_invalid_workspace_root() -> None:
    with pytest.raises(ValueError, match="absolute"):
        OrchestrationRequest(
            request_id="req-1",
            goal="build something",
            workspace_root="relative/path",
        )


def test_orchestration_request_accepts_valid_workspace_root(tmp_path: object) -> None:
    request = OrchestrationRequest(
        request_id="req-1",
        goal="build something",
        workspace_root=str(tmp_path),
    )
    assert request.workspace_root == str(tmp_path.resolve())  # type: ignore[union-attr]


def test_orchestration_request_workspace_root_defaults_to_none() -> None:
    request = OrchestrationRequest(request_id="req-1", goal="build something")
    assert request.workspace_root is None
