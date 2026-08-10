"""Stage 8C.1: the end-to-end orchestration application-service layer.

Composes the independently-certified Manager (Stage 8A/8B/8B.1), Planner,
Router, Workflow Engine, Verification/Recovery, Learning, Knowledge, and
Adaptive Retrieval subsystems into one reusable pipeline
(`EndToEndOrchestrationService`) -- see `service.py`'s module docstring for
the exact phase order and every authority boundary it preserves.

This package implements no new subsystem logic of its own: every phase
calls an existing, unmodified component. What it adds is only the glue
architecture discovery confirmed did not exist before Stage 8C.1 --
`runtime.py` (live `CandidateAgent` assembly for the Router),
`compiler.py` (`WorkflowPlan` -> the live `WorkflowCreate` schema),
`verification_adapter.py` (`StepAttempt` -> `ObservedOutcome`), and
`knowledge_adapter.py` (bridging Stage 6A's own `KnowledgeSearchResult`
into the Obsidian-shaped one `ManagerRequest`/`PlanningRequest` expect).

No FastAPI endpoints, SSE, WebSockets, CLI commands, or frontend wiring
live here -- those are Stage 8C.2/8C.3. No live NVIDIA/Claude/Codex/Gemini
call is made by anything in this package; a `ManagerModel`/runtime
implementation is always injected by the caller.
"""

from app.engine.orchestration.models import (
    OrchestrationOutcome,
    OrchestrationRequest,
    OrchestrationResult,
)
from app.engine.orchestration.service import EndToEndOrchestrationService

__all__ = [
    "EndToEndOrchestrationService",
    "OrchestrationOutcome",
    "OrchestrationRequest",
    "OrchestrationResult",
]
