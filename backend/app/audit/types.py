"""Centralized audit event types and actor types.

Defined once here and imported everywhere an audit event is appended, so
event-type/actor-type strings are never invented independently in different
modules.
"""

from enum import StrEnum


class AuditEventType(StrEnum):
    WORKFLOW_CREATED = "workflow_created"
    WORKFLOW_EXECUTION_STARTED = "workflow_execution_started"
    WORKFLOW_SUCCEEDED = "workflow_succeeded"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_COMPENSATION_STARTED = "workflow_compensation_started"
    WORKFLOW_COMPENSATED = "workflow_compensated"
    WORKFLOW_COMPENSATION_FAILED = "workflow_compensation_failed"

    STEP_EXECUTION_STARTED = "step_execution_started"
    STEP_SUCCEEDED = "step_succeeded"
    STEP_FAILED = "step_failed"
    STEP_RETRY_SCHEDULED = "step_retry_scheduled"

    STEP_COMPENSATION_STARTED = "step_compensation_started"
    STEP_COMPENSATED = "step_compensated"
    STEP_COMPENSATION_FAILED = "step_compensation_failed"

    EXECUTION_ATTEMPT_STARTED = "execution_attempt_started"
    EXECUTION_ATTEMPT_SUCCEEDED = "execution_attempt_succeeded"
    EXECUTION_ATTEMPT_FAILED = "execution_attempt_failed"

    COMPENSATION_ATTEMPT_STARTED = "compensation_attempt_started"
    COMPENSATION_ATTEMPT_SUCCEEDED = "compensation_attempt_succeeded"
    COMPENSATION_ATTEMPT_FAILED = "compensation_attempt_failed"

    CIRCUIT_BREAKER_REJECTED = "circuit_breaker_rejected"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"
    COMPENSATION_HANDLER = "compensation_handler"
