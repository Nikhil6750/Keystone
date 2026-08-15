"""Base protocol and interfaces for Stage 9D Quality Gate Executors."""

from __future__ import annotations

from typing import Protocol

from app.contracts.quality import (
    QualityExecutionContext,
    QualityGateResult,
    QualityGateSpec,
)


class QualityGateExecutor(Protocol):
    """Provider-neutral interface for executing a quality gate against a workspace."""

    def execute(
        self,
        spec: QualityGateSpec,
        context: QualityExecutionContext,
    ) -> QualityGateResult:
        """Execute the gate check and return a structured, evidence-backed result."""
        ...


__all__ = ["QualityGateExecutor"]
