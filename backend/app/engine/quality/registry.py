"""Quality Gate Executor Registry for managing provider-neutral verification executors."""

from __future__ import annotations

from app.contracts.quality import QualityGateType
from app.engine.quality.errors import QualityGateExecutionError
from app.engine.quality.executors.base import QualityGateExecutor
from app.engine.quality.executors.build_executor import BuildQualityGateExecutor
from app.engine.quality.executors.custom_executor import DeterministicCommandQualityGateExecutor
from app.engine.quality.executors.lint_executor import LintQualityGateExecutor
from app.engine.quality.executors.test_executor import TestQualityGateExecutor
from app.engine.quality.executors.type_check_executor import TypeCheckQualityGateExecutor


class QualityGateExecutorRegistry:
    """Registry mapping gate types to concrete provider-neutral executors."""

    def __init__(self) -> None:
        self._executors: dict[str, QualityGateExecutor] = {}

    def register_executor(
        self,
        gate_type: QualityGateType | str,
        executor: QualityGateExecutor,
    ) -> None:
        """Register an executor for a specific quality gate type."""
        key = gate_type.value if isinstance(gate_type, QualityGateType) else str(gate_type).lower()
        self._executors[key] = executor

    def get_executor(self, gate_type: QualityGateType | str) -> QualityGateExecutor:
        """Retrieve the executor registered for a gate type."""
        key = gate_type.value if isinstance(gate_type, QualityGateType) else str(gate_type).lower()
        executor = self._executors.get(key)
        if executor is None:
            raise QualityGateExecutionError(
                f"No QualityGateExecutor registered for gate type '{gate_type}'."
            )
        return executor

    @classmethod
    def default_registry(cls) -> QualityGateExecutorRegistry:
        """Construct standard registry with built-in quality gate executors."""
        reg = cls()
        reg.register_executor(QualityGateType.TEST, TestQualityGateExecutor())
        reg.register_executor(QualityGateType.LINT, LintQualityGateExecutor())
        reg.register_executor(QualityGateType.TYPE_CHECK, TypeCheckQualityGateExecutor())
        reg.register_executor(QualityGateType.BUILD, BuildQualityGateExecutor())
        reg.register_executor(QualityGateType.CUSTOM, DeterministicCommandQualityGateExecutor())
        return reg


__all__ = ["QualityGateExecutorRegistry"]
