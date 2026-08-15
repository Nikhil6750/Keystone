"""Stage 9E: Engineering Intelligence Graph.

A deterministic, evidence-backed projection of execution/quality evidence
Keystone already persists (Stage 8C.1 orchestration, Stage 9C Verified
Skill Foundry, Stage 9D Software Quality Factory) into a queryable graph --
see `app.engine.intelligence.builder` for ingestion and
`app.engine.intelligence.query_service` for reads. This package owns no
execution, workflow, skill, or quality authority of its own; it is
downstream analytical state (see both modules' docstrings).
"""

from app.engine.intelligence.builder import EngineeringIntelligenceGraphBuilder, IngestionSummary
from app.engine.intelligence.graph_repository import (
    InMemoryIntelligenceGraphRepository,
    IntelligenceGraphRepository,
    SqlAlchemyIntelligenceGraphRepository,
)
from app.engine.intelligence.query_service import EngineeringIntelligenceQueryService

__all__ = [
    "EngineeringIntelligenceGraphBuilder",
    "EngineeringIntelligenceQueryService",
    "InMemoryIntelligenceGraphRepository",
    "IngestionSummary",
    "IntelligenceGraphRepository",
    "SqlAlchemyIntelligenceGraphRepository",
]
