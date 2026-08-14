"""Live Workspace File Activity Monitor.

Bounded, workspace-scoped, symlink-safe file activity monitor for live project execution.
Observes file creation, modification, and deletion within the approved workspace.
Excludes .git, node_modules, .venv, dist, build, and cache directories.
Never reads or logs file contents.
Emits safe file_activity events with relative paths and activity type.
"""

import asyncio
import contextlib
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXCLUDED_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".cache",
    ".idea",
    ".vscode",
}


class FileActivityEvent:
    """Safe event representing live workspace file activity."""

    def __init__(
        self,
        relative_path: str,
        activity: str,  # "created" | "modified" | "deleted"
        task_id: str | None = None,
        agent_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.relative_path = relative_path
        self.activity = activity
        self.task_id = task_id
        self.agent_id = agent_id
        self.timestamp = timestamp or datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "activity": self.activity,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
        }


class WorkspaceWatcher:
    """Symlink-safe, bounded workspace activity watcher with concurrent file attribution."""

    def __init__(
        self,
        workspace_root: str | Path,
        on_activity: Callable[[FileActivityEvent], Any] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.on_activity = on_activity
        self.poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._snapshot: dict[str, float] = {}
        # task_id -> (agent_id, set_of_normalized_target_files)
        self._active_tasks: dict[str, tuple[str, set[str]]] = {}
        self.active_task_id: str | None = None
        self.active_agent_id: str | None = None

    async def start_async(self) -> None:
        """Start polling workspace for changes within an active event loop."""
        if self._running:
            return
        self._running = True
        self._snapshot = self._take_snapshot()
        self._task = asyncio.create_task(self._poll_loop())

    async def stop_async(self) -> None:
        """Stop polling workspace safely within an active event loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    def register_active_task(self, task_id: str, agent_id: str, target_files: list[str]) -> None:
        """Register a currently running task and its target files for concurrent attribution."""
        norm_files = {str(Path(f)).replace("\\", "/") for f in target_files}
        self._active_tasks[task_id] = (agent_id, norm_files)

    def unregister_active_task(self, task_id: str) -> None:
        """Unregister a completed task from active attribution."""
        self._active_tasks.pop(task_id, None)

    def set_active_context(self, task_id: str | None, agent_id: str | None) -> None:
        """Legacy helper for single-task execution context."""
        self.active_task_id = task_id
        self.active_agent_id = agent_id

    def _resolve_attribution(self, rel_path: str) -> tuple[str | None, str | None]:
        """Attribute a file change safely across concurrent active tasks."""
        if not self._active_tasks:
            return self.active_task_id, self.active_agent_id

        matching: list[tuple[str, str]] = []
        for t_id, (a_id, target_files) in self._active_tasks.items():
            if rel_path in target_files or any(
                rel_path.endswith(tf) or tf.endswith(rel_path) for tf in target_files
            ):
                matching.append((t_id, a_id))

        if len(matching) == 1:
            return matching[0]

        # If exactly one task is active, attribute to it even if target_files was unlisted
        if len(self._active_tasks) == 1:
            single_t_id, (single_a_id, _) = next(iter(self._active_tasks.items()))
            return single_t_id, single_a_id

        # Ambiguous or multiple tasks active -> workflow level change
        return None, None

    def poll_now(self) -> list[FileActivityEvent]:
        """Perform a single immediate check for changes and emit events."""
        current = self._take_snapshot()
        events: list[FileActivityEvent] = []

        # Created or modified
        for rel_path, mtime in current.items():
            if rel_path not in self._snapshot:
                t_id, a_id = self._resolve_attribution(rel_path)
                events.append(
                    FileActivityEvent(
                        relative_path=rel_path,
                        activity="created",
                        task_id=t_id,
                        agent_id=a_id,
                    )
                )
            elif mtime > self._snapshot[rel_path]:
                t_id, a_id = self._resolve_attribution(rel_path)
                events.append(
                    FileActivityEvent(
                        relative_path=rel_path,
                        activity="modified",
                        task_id=t_id,
                        agent_id=a_id,
                    )
                )

        # Deleted
        for rel_path in self._snapshot:
            if rel_path not in current:
                t_id, a_id = self._resolve_attribution(rel_path)
                events.append(
                    FileActivityEvent(
                        relative_path=rel_path,
                        activity="deleted",
                        task_id=t_id,
                        agent_id=a_id,
                    )
                )

        self._snapshot = current

        if self.on_activity:
            for event in events:
                try:
                    res = self.on_activity(event)
                    if asyncio.iscoroutine(res):
                        asyncio.create_task(res)
                except Exception:
                    pass

        return events

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                self.poll_now()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def _take_snapshot(self) -> dict[str, float]:
        """Scan workspace for file modification timestamps safely."""
        snapshot: dict[str, float] = {}
        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            return snapshot

        try:
            for root, dirs, files in os.walk(str(self.workspace_root), followlinks=False):
                # Exclude directories in-place
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES and not d.startswith(".")]

                root_path = Path(root)
                # Symlink safety check: ensure root_path remains inside workspace_root
                try:
                    resolved_root = root_path.resolve()
                    if not resolved_root.is_relative_to(self.workspace_root):
                        continue
                except ValueError:
                    continue

                for f in files:
                    file_path = root_path / f
                    try:
                        resolved_file = file_path.resolve()
                        if not resolved_file.is_relative_to(self.workspace_root):
                            continue
                        rel = resolved_file.relative_to(self.workspace_root)
                        rel_path = str(rel).replace("\\", "/")
                        mtime = file_path.stat().st_mtime
                        snapshot[rel_path] = mtime
                    except (OSError, ValueError):
                        continue
        except OSError:
            pass

        return snapshot


__all__ = ["EXCLUDED_DIR_NAMES", "FileActivityEvent", "WorkspaceWatcher"]
