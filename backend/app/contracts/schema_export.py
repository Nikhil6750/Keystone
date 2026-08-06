"""Generates JSON Schema artifacts for every canonical contract model.

Used by `backend/scripts/export_contracts.py` and by
`tests/test_contracts_schema_export.py` to keep `backend/contracts/schemas/`
in sync with the Pydantic models. Developer 2 and Developer 3 consume the
generated `.schema.json` files directly; they never hand-write a second copy
of these shapes.
"""

import json
from pathlib import Path

from pydantic import BaseModel

from app.contracts.adapter import (
    AgentDescriptor,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentUsage,
    RepositoryMetadata,
)
from app.contracts.benchmark import BenchmarkDefinition, BenchmarkResult, BenchmarkTask
from app.contracts.knowledge import KnowledgeDocument, KnowledgeSearchResult
from app.contracts.passports import AgentPassport, AgentPassportMetricBucket
from app.contracts.routing import RoutingCandidateScore, RoutingDecision, RoutingRequest
from app.contracts.workflow import (
    WorkflowDefinition,
    WorkflowExecutionEvent,
    WorkflowStepDefinition,
)
from app.schemas.errors import APIErrorEnvelope

# The canonical name -> model registry. `ErrorResponse` maps to the existing,
# already-shipping `APIErrorEnvelope` (`app.schemas.errors`) rather than a
# second handwritten copy, per the "no duplicate incompatible contracts" rule.
CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "AgentDescriptor": AgentDescriptor,
    "AgentExecutionRequest": AgentExecutionRequest,
    "AgentExecutionResult": AgentExecutionResult,
    "AgentUsage": AgentUsage,
    "RepositoryMetadata": RepositoryMetadata,
    "WorkflowDefinition": WorkflowDefinition,
    "WorkflowStepDefinition": WorkflowStepDefinition,
    "WorkflowExecutionEvent": WorkflowExecutionEvent,
    "RoutingRequest": RoutingRequest,
    "RoutingCandidateScore": RoutingCandidateScore,
    "RoutingDecision": RoutingDecision,
    "AgentPassport": AgentPassport,
    "AgentPassportMetricBucket": AgentPassportMetricBucket,
    "KnowledgeDocument": KnowledgeDocument,
    "KnowledgeSearchResult": KnowledgeSearchResult,
    "BenchmarkDefinition": BenchmarkDefinition,
    "BenchmarkTask": BenchmarkTask,
    "BenchmarkResult": BenchmarkResult,
    "ErrorResponse": APIErrorEnvelope,
}


def export_all_schemas(output_dir: Path) -> list[Path]:
    """Write one `<Name>.schema.json` file per contract model into `output_dir`.

    Returns the sorted list of written paths. `output_dir` is created if it
    does not already exist.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in CONTRACT_MODELS.items():
        path = output_dir / f"{name}.schema.json"
        path.write_text(_dump_schema(model), encoding="utf-8")
        written.append(path)
    return sorted(written)


def _dump_schema(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


__all__ = ["CONTRACT_MODELS", "export_all_schemas"]
