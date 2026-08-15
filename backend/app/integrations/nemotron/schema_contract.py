"""Derives a compact, deterministic textual output-contract description of
`ManagerResponse` directly from `ManagerResponse.model_json_schema()` --
the single source of truth for field names, required-ness, nested object
shapes, and enum values (Stage 8B.1 Part A: "do not manually maintain a
second independent copy of ManagerResponse's schema").

Every fact about *which fields exist, which are required, what type each
has, and which enum values are allowed* is read from the live Pydantic
schema at import time -- never hardcoded here. If `ManagerResponse` (or
`ManagerTaskProposal`/`ManagerEvidenceRef`) gains, loses, or renames a
field, this module's output changes automatically the next time it runs;
nothing here needs editing to stay correct.

Two kinds of information genuinely cannot come from `model_json_schema()`,
and are the only hand-written parts of this module:

1. `ManagerResponse`'s two cross-field `model_validator` invariants
   (`clarification_question` <-> `clarification_required` pairing, and
   `task_proposals[].depends_on` referencing sibling `key` values with no
   cycles) -- a JSON Schema document has no vocabulary for "this field's
   presence depends on that field's value" or "this array must reference
   another array's items by a field", so these are described in prose.
2. A handful of collection/length bounds enforced by custom
   `@field_validator`s rather than native Pydantic `Field(min_length=...)`/
   `Field(le=...)` constraints, so they do not appear in
   `model_json_schema()` at all. These are sourced from
   `app.engine.manager.models`' own exported `MAX_*` constants -- never a
   hand-copied bare number -- so a bound change there is reflected here
   automatically too. A field's bound not appearing in `_BOUND_HINTS`/
   `_TASK_PROPOSAL_BOUND_HINTS` below does not weaken anything: the
   Pydantic validator remains fully authoritative regardless of what this
   prompt text does or doesn't mention.

**Deterministic.** `model_json_schema()` is a pure function of the class
definition, and this module walks its `properties` dicts in their own
(field-declaration-preserving) order. The same source code always produces
the same byte-for-byte contract string -- see `MANAGER_RESPONSE_CONTRACT`,
computed once at import time.
"""

from typing import Any

from app.engine.manager.models import (
    MAX_CAPABILITIES_PER_TASK,
    MAX_CLARIFICATION_QUESTION_LENGTH,
    MAX_DEPENDENCIES_PER_TASK,
    MAX_EVIDENCE_ITEMS,
    MAX_GOAL_INTERPRETATION_LENGTH,
    MAX_KNOWLEDGE_NEEDS,
    MAX_PREFERRED_AGENTS_PER_TASK,
    MAX_TASK_DESCRIPTION_LENGTH,
    MAX_TASK_PROPOSALS,
    MAX_WARNINGS,
    ManagerResponse,
)

_BOUND_HINTS: dict[str, str] = {
    "task_proposals": f"max {MAX_TASK_PROPOSALS} items",
    "requested_knowledge_queries": f"max {MAX_KNOWLEDGE_NEEDS} items",
    "evidence_summary": f"max {MAX_EVIDENCE_ITEMS} items",
    "warnings": f"max {MAX_WARNINGS} items",
    "goal_interpretation": f"max {MAX_GOAL_INTERPRETATION_LENGTH} characters",
    "clarification_question": f"max {MAX_CLARIFICATION_QUESTION_LENGTH} characters",
    "confidence": "range 0.0 to 1.0",
}

_TASK_PROPOSAL_BOUND_HINTS: dict[str, str] = {
    "description": f"max {MAX_TASK_DESCRIPTION_LENGTH} characters",
    "required_capabilities": f"max {MAX_CAPABILITIES_PER_TASK} items",
    "depends_on": f"max {MAX_DEPENDENCIES_PER_TASK} items",
    "preferred_agent_types": f"max {MAX_PREFERRED_AGENTS_PER_TASK} items",
}


def _resolve(node: dict[str, Any], defs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Follow one `$ref` (if present) into `defs`; otherwise return `node`
    unchanged. `ManagerResponse`'s schema never nests `$ref` more than one
    level deep, so a single resolution step is always sufficient."""
    if "$ref" in node:
        name = str(node["$ref"]).rsplit("/", 1)[-1]
        return defs[name]
    return node


def _describe_type(node: dict[str, Any], defs: dict[str, dict[str, Any]]) -> str:
    """A short, human-readable type description for one JSON Schema node,
    resolving `$ref` and the `anyOf`-nullable wrapping Pydantic v2 emits
    for `X | None` fields, generically -- not per-field-hardcoded."""
    if "anyOf" in node:
        branches = [b for b in node["anyOf"] if b.get("type") != "null"]
        nullable = any(b.get("type") == "null" for b in node["anyOf"])
        described = " or ".join(_describe_type(b, defs) for b in branches)
        return f"{described} or null" if nullable else described

    node = _resolve(node, defs)

    if "enum" in node:
        values = " | ".join(f'"{value}"' for value in node["enum"])
        return f"one of {values}"

    node_type = node.get("type")
    if node_type == "array":
        item_description = _describe_type(node.get("items", {}), defs)
        return f"array of ({item_description})"
    if node_type == "object":
        return str(node.get("title", "object"))
    if node_type in {"string", "integer", "number", "boolean"}:
        return str(node_type)
    return "any"


def _describe_object_fields(
    schema: dict[str, Any], defs: dict[str, dict[str, Any]], bound_hints: dict[str, str]
) -> list[str]:
    """One `- name: type (REQUIRED|optional[, bound])` line per property,
    in the schema's own declared order."""
    required = set(schema.get("required", ()))
    lines: list[str] = []
    for name, node in schema.get("properties", {}).items():
        type_description = _describe_type(node, defs)
        required_description = "REQUIRED" if name in required else "optional"
        bound = bound_hints.get(name)
        suffix = f", {bound}" if bound else ""
        lines.append(f"  - {name}: {type_description} ({required_description}{suffix})")
    return lines


def build_manager_response_contract() -> str:
    """A compact, deterministic textual output contract for
    `ManagerResponse`, derived from `ManagerResponse.model_json_schema()`.
    See the module docstring for exactly what is schema-derived versus the
    small amount of unavoidable hand-written prose."""
    schema = ManagerResponse.model_json_schema()
    defs: dict[str, dict[str, Any]] = schema.get("$defs", {})
    task_proposal_schema = defs["ManagerTaskProposal"]
    evidence_ref_schema = defs["ManagerEvidenceRef"]

    lines = [
        "Return exactly one JSON object conforming to this schema.",
        "",
        "Top-level ManagerResponse object fields:",
        *_describe_object_fields(schema, defs, _BOUND_HINTS),
        "",
        "No fields beyond exactly this list are permitted on the top-level "
        "object (additional/unknown properties are rejected). Do not rename "
        "any field.",
        "",
        "Each task_proposals[] item is a ManagerTaskProposal object with exactly these fields:",
        *_describe_object_fields(task_proposal_schema, defs, _TASK_PROPOSAL_BOUND_HINTS),
        "",
        "No fields beyond exactly this list are permitted on a "
        "ManagerTaskProposal (additional/unknown properties are rejected). "
        "Do not add agent_type, task_id, capability, inputs, or "
        "expected_outputs -- none of these exist in this schema. The task "
        "identifier field is named 'key', never 'task_id'. "
        "required_capabilities is always a JSON array, never a single "
        "string field named 'capability'. Every entry in a task's "
        "depends_on array must exactly equal another task_proposals[].key "
        "value present in this same response; task_proposals keys must be "
        "unique within the response and must not form a dependency cycle.",
        "",
        "Each evidence_summary[] item is a ManagerEvidenceRef object with exactly these fields:",
        *_describe_object_fields(evidence_ref_schema, defs, {}),
        "",
        "No fields beyond exactly this list are permitted on a "
        "ManagerEvidenceRef (additional/unknown properties are rejected). "
        "evidence_summary itself must be a JSON array, never an object.",
        "",
        "clarification_question must be present and non-empty if and only "
        "if clarification_required is true; omit clarification_question "
        "entirely (or leave it absent) when clarification_required is "
        "false or omitted.",
    ]
    return "\n".join(lines)


MANAGER_RESPONSE_CONTRACT = build_manager_response_contract()

__all__ = ["MANAGER_RESPONSE_CONTRACT", "build_manager_response_contract"]
