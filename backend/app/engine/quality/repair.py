"""Bounded Repair Management and structured diagnostic packet formatting."""

from __future__ import annotations

from datetime import UTC, datetime

from app.contracts.quality import (
    QualityGateStatus,
    QualityRepairPacket,
    QualityRun,
)


class QualityRepairManager:
    """Constructs structured, factual repair packets from failed quality runs

    for bounded ingestion by existing KeyStone orchestration retry loops.
    """

    DEFAULT_MAX_REPAIR_ATTEMPTS = 3

    def build_repair_packet(
        self,
        run: QualityRun,
        max_repair_attempts: int | None = None,
    ) -> QualityRepairPacket | None:
        """Create structured repair context if blocking gate failures occurred
        and repair budget remains.
        """
        if not run.verdict or run.verdict.passed:
            return None

        max_attempts = max_repair_attempts or self.DEFAULT_MAX_REPAIR_ATTEMPTS
        if run.attempt_number >= max_attempts:
            # Repair attempts exhausted
            return None

        blocking_gates = [
            r
            for r in run.gate_results
            if r.required and r.status in (QualityGateStatus.FAILED, QualityGateStatus.ERROR)
        ]
        if not blocking_gates:
            return None

        blocking_ids: list[str] = [g.gate_id for g in blocking_gates]
        summaries: list[str] = [
            g.failure_reason or f"Gate '{g.name}' failed" for g in blocking_gates
        ]

        diagnostics: list[str] = []
        artifacts: list[str] = []

        for g in blocking_gates:
            if g.evidence:
                diagnostics.extend(g.evidence.diagnostics)
                artifacts.extend(g.evidence.artifact_references)

        return QualityRepairPacket(
            run_id=run.run_id,
            task_id=run.task_id or "",
            execution_id=run.execution_id,
            attempt_number=run.attempt_number,
            max_repair_attempts=max_attempts,
            blocking_gate_ids=tuple(blocking_ids),
            failure_summaries=tuple(summaries),
            diagnostics=tuple(diagnostics[:30]),
            affected_artifacts=tuple(sorted(set(artifacts))),
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def format_repair_prompt_section(packet: QualityRepairPacket) -> str:
        """Format bounded factual repair guidance to inject into an agent's retry attempt prompt."""
        fail_count = len(packet.blocking_gate_ids)
        lines = [
            "### REQUIRED QUALITY VERIFICATION REPAIR NOTICE",
            (
                f"Previous attempt #{packet.attempt_number} failed "
                f"{fail_count} required quality gate(s)."
            ),
            f"Repair attempt #{packet.attempt_number + 1} of {packet.max_repair_attempts}.",
            "",
            "**Blocking Failures:**",
        ]
        for s in packet.failure_summaries:
            lines.append(f"- {s}")

        if packet.diagnostics:
            lines.append("\n**Factual Diagnostics:**")
            for d in packet.diagnostics[:10]:
                lines.append(f"  * {d}")

        if packet.affected_artifacts:
            lines.append("\n**Affected Artifacts:**")
            for a in packet.affected_artifacts:
                lines.append(f"  * {a}")

        lines.append(
            "\nPlease repair the code so that all required quality gates pass. "
            "Do not state that checks passed without resolving the underlying failure."
        )
        return "\n".join(lines)


__all__ = ["QualityRepairManager"]
