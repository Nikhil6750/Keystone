"""Stage 8A: provider-neutral manager core + deterministic orchestration
boundary.

The LLM manager is advisory/reasoning intelligence; Keystone's deterministic
systems (`app.engine.planning.planner.Planner`, `app.engine.routing.router.Router`,
`app.engine.workflow_engine.WorkflowEngine`, `app.engine.verification`,
`app.engine.learning`) remain fully authoritative. A `ManagerModel`
(`protocol.py`) can only PROPOSE a structured `ManagerResponse` (`models.py`);
`ManagerProposalValidator` (`validation.py`) deterministically validates it
before `ManagerOrchestrator` (`orchestrator.py`) may fold any part of it into
an existing, unmodified Keystone component's input. See each module's
docstring for the full architecture and the exact boundary each one enforces.

This package has **no** NVIDIA/OpenAI/Anthropic SDK import and **no**
provider-specific networking -- that is Stage 8B's job, not this one's.
"""

from app.engine.manager.context import build_manager_request
from app.engine.manager.errors import (
    ManagerError,
    ManagerInvalidResponseError,
    ManagerProposalRejectedError,
    ManagerTimeoutError,
    ManagerUnavailableError,
)
from app.engine.manager.fake import FakeManagerModel
from app.engine.manager.models import (
    ManagerEvidenceRef,
    ManagerRecoveryContext,
    ManagerRequest,
    ManagerResponse,
    ManagerTaskProposal,
)
from app.engine.manager.orchestrator import (
    ManagerOrchestrationPolicy,
    ManagerOrchestrationResult,
    ManagerOrchestrator,
)
from app.engine.manager.protocol import ManagerModel, parse_manager_response
from app.engine.manager.validation import (
    ManagerProposalValidator,
    ManagerValidationIssue,
    ManagerValidationResult,
)

__all__ = [
    "FakeManagerModel",
    "ManagerError",
    "ManagerEvidenceRef",
    "ManagerInvalidResponseError",
    "ManagerModel",
    "ManagerOrchestrationPolicy",
    "ManagerOrchestrationResult",
    "ManagerOrchestrator",
    "ManagerProposalRejectedError",
    "ManagerProposalValidator",
    "ManagerRecoveryContext",
    "ManagerRequest",
    "ManagerResponse",
    "ManagerTaskProposal",
    "ManagerTimeoutError",
    "ManagerUnavailableError",
    "ManagerValidationIssue",
    "ManagerValidationResult",
    "build_manager_request",
    "parse_manager_response",
]
