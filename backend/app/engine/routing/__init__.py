"""Explainable, evidence-based agent routing foundation (Stage 4B).

Deliberately not "AI routing" or "self-learning": every decision is a
deterministic function of its inputs (capability match, live availability,
circuit-breaker state, and historical evidence), and every decision carries
a human-readable explanation. No external model is ever called to select an
agent.

`request_builder.py` translates a Planner's `TaskSpec` into a `RoutingRequest`
without re-classifying its already-authoritative `task_type`; `router.py`
filters candidates against `RoutingConstraints`' hard constraints (excluded
types, missing capability, unavailable/circuit-open, unmet
reliability/latency/cost thresholds — never treating missing evidence as
compliant) before `scorer.py` scores the remaining eligible candidates on
eight deterministic, sample-size-aware factors and `router.py` selects a
single primary, an ordered fallback list, or (for
`RoutingConstraints.allow_parallel`/`consensus_size`) a full selected set.

Historical evidence (success rates, latency, task-type/repository-specific
performance, cost) is queried through the `RoutingEvidenceProvider` protocol
(`evidence.py`), not computed here — `NullEvidenceProvider` (used by
default) reports no data for everything, so the router works today against
zero history and needs no code change once Stage 5's agent-passport
aggregation supplies a real implementation of the same protocol.
"""
