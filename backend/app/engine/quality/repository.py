"""Persistence layer and repository abstractions for Stage 9D Quality Factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.contracts.quality import QualityGateResult, QualityProfile, QualityRun
from app.engine.quality.errors import QualityError
from app.models.quality import (
    QualityGateResultRecord,
    QualityProfileRecord,
    QualityRunRecord,
)


class QualityRepository(Protocol):
    """Protocol defining persistence operations for quality profiles and runs."""

    def save_profile(self, profile: QualityProfile) -> None: ...

    def get_profile(self, profile_id: str) -> QualityProfile | None: ...

    def get_default_profile(self) -> QualityProfile | None: ...

    def list_profiles(self) -> list[QualityProfile]: ...

    def save_run(self, run: QualityRun) -> None: ...

    def get_run(self, run_id: str) -> QualityRun | None: ...

    def get_runs_by_execution(self, execution_id: str) -> list[QualityRun]: ...

    def get_runs_by_task(self, task_id: str) -> list[QualityRun]: ...

    def get_runs_by_workflow(self, workflow_id: str) -> list[QualityRun]: ...

    def get_gate_results_for_run(self, run_id: str) -> list[QualityGateResult]: ...

    def get_latest_run_for_task(
        self, task_id: str, execution_id: str | None = None
    ) -> QualityRun | None: ...


class InMemoryQualityRepository:
    """Deterministic in-memory quality repository for unit testing and fast mocking."""

    def __init__(self) -> None:
        self._profiles: dict[str, QualityProfile] = {}
        self._runs: dict[str, QualityRun] = {}
        self._gate_results: dict[str, list[QualityGateResult]] = {}  # run_id -> results

    def save_profile(self, profile: QualityProfile) -> None:
        if profile.is_default:
            # Clear previous default
            for pid, p in list(self._profiles.items()):
                if p.is_default and pid != profile.profile_id:
                    self._profiles[pid] = QualityProfile(
                        profile_id=p.profile_id,
                        name=p.name,
                        description=p.description,
                        target_languages=p.target_languages,
                        target_frameworks=p.target_frameworks,
                        gates=p.gates,
                        is_default=False,
                        metadata=p.metadata,
                    )
        self._profiles[profile.profile_id] = profile

    def get_profile(self, profile_id: str) -> QualityProfile | None:
        return self._profiles.get(profile_id)

    def get_default_profile(self) -> QualityProfile | None:
        for p in self._profiles.values():
            if p.is_default:
                return p
        return None

    def list_profiles(self) -> list[QualityProfile]:
        return sorted(self._profiles.values(), key=lambda p: p.profile_id)

    def save_run(self, run: QualityRun) -> None:
        self._runs[run.run_id] = run
        self._gate_results[run.run_id] = list(run.gate_results)

    def get_run(self, run_id: str) -> QualityRun | None:
        return self._runs.get(run_id)

    def get_runs_by_execution(self, execution_id: str) -> list[QualityRun]:
        return [r for r in self._runs.values() if r.execution_id == execution_id]

    def get_runs_by_task(self, task_id: str) -> list[QualityRun]:
        return [r for r in self._runs.values() if r.task_id == task_id]

    def get_runs_by_workflow(self, workflow_id: str) -> list[QualityRun]:
        return [r for r in self._runs.values() if r.workflow_id == workflow_id]

    def get_gate_results_for_run(self, run_id: str) -> list[QualityGateResult]:
        return list(self._gate_results.get(run_id, []))

    def get_latest_run_for_task(
        self, task_id: str, execution_id: str | None = None
    ) -> QualityRun | None:
        matching = [
            r
            for r in self._runs.values()
            if r.task_id == task_id and (execution_id is None or r.execution_id == execution_id)
        ]
        if not matching:
            return None
        return max(matching, key=lambda r: (r.attempt_number, r.created_at))


class SqlAlchemyQualityRepository:
    """Production-grade SQLAlchemy persistence for Quality Profiles, Runs, and Gate Results."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save_profile(self, profile: QualityProfile) -> None:
        with self._session_factory() as session:
            try:
                if profile.is_default:
                    # Unset other defaults
                    existing_defaults = session.scalars(
                        select(QualityProfileRecord).where(
                            QualityProfileRecord.is_default.is_(True)
                        )
                    ).all()
                    for ed in existing_defaults:
                        if ed.profile_id != profile.profile_id:
                            ed.is_default = False

                existing = session.get(QualityProfileRecord, profile.profile_id)
                new_rec = QualityProfileRecord.from_contract(profile)
                if existing:
                    existing.name = new_rec.name
                    existing.description = new_rec.description
                    existing.target_languages = new_rec.target_languages
                    existing.target_frameworks = new_rec.target_frameworks
                    existing.gates = new_rec.gates
                    existing.is_default = new_rec.is_default
                    existing.metadata_json = new_rec.metadata_json
                else:
                    session.add(new_rec)
                session.commit()
            except Exception as exc:
                session.rollback()
                raise QualityError(f"Failed to save quality profile: {exc}") from exc

    def get_profile(self, profile_id: str) -> QualityProfile | None:
        with self._session_factory() as session:
            rec = session.get(QualityProfileRecord, profile_id)
            return rec.to_contract() if rec else None

    def get_default_profile(self) -> QualityProfile | None:
        with self._session_factory() as session:
            stmt = (
                select(QualityProfileRecord)
                .where(QualityProfileRecord.is_default.is_(True))
                .limit(1)
            )
            rec = session.scalars(stmt).first()
            return rec.to_contract() if rec else None

    def list_profiles(self) -> list[QualityProfile]:
        with self._session_factory() as session:
            stmt = select(QualityProfileRecord).order_by(QualityProfileRecord.profile_id)
            records = session.scalars(stmt).all()
            return [r.to_contract() for r in records]

    def save_run(self, run: QualityRun) -> None:
        with self._session_factory() as session:
            try:
                # 1. Upsert QualityRunRecord
                stmt = (
                    select(QualityRunRecord)
                    .where(
                        (QualityRunRecord.run_id == run.run_id)
                        | (
                            (QualityRunRecord.execution_id == run.execution_id)
                            & (QualityRunRecord.task_id == run.task_id)
                            & (QualityRunRecord.attempt_number == run.attempt_number)
                        )
                    )
                    .limit(1)
                )
                existing_run = session.scalars(stmt).first()
                new_run_rec = QualityRunRecord.from_contract(run)
                if existing_run:
                    existing_run.status = new_run_rec.status
                    existing_run.passed = new_run_rec.passed
                    existing_run.total_gates = new_run_rec.total_gates
                    existing_run.passed_gates = new_run_rec.passed_gates
                    existing_run.failed_gates = new_run_rec.failed_gates
                    existing_run.skipped_gates = new_run_rec.skipped_gates
                    existing_run.error_gates = new_run_rec.error_gates
                    existing_run.summary_explanation = new_run_rec.summary_explanation
                    existing_run.completed_at = new_run_rec.completed_at
                    target_run_id = existing_run.run_id
                else:
                    session.add(new_run_rec)
                    target_run_id = run.run_id

                # 2. Persist Gate Results
                for gr in run.gate_results:
                    stmt_gr = (
                        select(QualityGateResultRecord)
                        .where(
                            QualityGateResultRecord.run_id == target_run_id,
                            QualityGateResultRecord.gate_id == gr.gate_id,
                        )
                        .limit(1)
                    )
                    existing_gr = session.scalars(stmt_gr).first()
                    if not existing_gr:
                        gr_rec = QualityGateResultRecord.from_contract(
                            gr,
                            run_id=target_run_id,
                            execution_id=run.execution_id,
                            task_id=run.task_id,
                            attempt_number=run.attempt_number,
                        )
                        session.add(gr_rec)

                session.commit()
            except Exception as exc:
                session.rollback()
                raise QualityError(f"Failed to save quality run '{run.run_id}': {exc}") from exc

    def get_gate_results_for_run(self, run_id: str) -> list[QualityGateResult]:
        with self._session_factory() as session:
            stmt = (
                select(QualityGateResultRecord)
                .where(QualityGateResultRecord.run_id == run_id)
                .order_by(QualityGateResultRecord.timestamp)
            )
            records = session.scalars(stmt).all()
            return [r.to_contract() for r in records]

    def get_run(self, run_id: str) -> QualityRun | None:
        with self._session_factory() as session:
            run_rec = session.get(QualityRunRecord, run_id)
            if not run_rec:
                return None
            gate_results = self.get_gate_results_for_run(run_id)
            return run_rec.to_contract(gate_results)

    def get_runs_by_execution(self, execution_id: str) -> list[QualityRun]:
        with self._session_factory() as session:
            stmt = (
                select(QualityRunRecord)
                .where(QualityRunRecord.execution_id == execution_id)
                .order_by(QualityRunRecord.attempt_number, QualityRunRecord.created_at)
            )
            records = session.scalars(stmt).all()
            results: list[QualityRun] = []
            for r in records:
                gates = self.get_gate_results_for_run(r.run_id)
                results.append(r.to_contract(gates))
            return results

    def get_runs_by_task(self, task_id: str) -> list[QualityRun]:
        with self._session_factory() as session:
            stmt = (
                select(QualityRunRecord)
                .where(QualityRunRecord.task_id == task_id)
                .order_by(QualityRunRecord.attempt_number, QualityRunRecord.created_at)
            )
            records = session.scalars(stmt).all()
            results: list[QualityRun] = []
            for r in records:
                gates = self.get_gate_results_for_run(r.run_id)
                results.append(r.to_contract(gates))
            return results

    def get_runs_by_workflow(self, workflow_id: str) -> list[QualityRun]:
        with self._session_factory() as session:
            stmt = (
                select(QualityRunRecord)
                .where(QualityRunRecord.workflow_id == workflow_id)
                .order_by(QualityRunRecord.created_at)
            )
            records = session.scalars(stmt).all()
            results: list[QualityRun] = []
            for r in records:
                gates = self.get_gate_results_for_run(r.run_id)
                results.append(r.to_contract(gates))
            return results

    def get_latest_run_for_task(
        self, task_id: str, execution_id: str | None = None
    ) -> QualityRun | None:
        with self._session_factory() as session:
            query = select(QualityRunRecord).where(QualityRunRecord.task_id == task_id)
            if execution_id:
                query = query.where(QualityRunRecord.execution_id == execution_id)
            query = query.order_by(
                desc(QualityRunRecord.attempt_number), desc(QualityRunRecord.created_at)
            ).limit(1)
            rec = session.scalars(query).first()
            if not rec:
                return None
            gates = self.get_gate_results_for_run(rec.run_id)
            return rec.to_contract(gates)


__all__ = [
    "InMemoryQualityRepository",
    "QualityRepository",
    "SqlAlchemyQualityRepository",
]
