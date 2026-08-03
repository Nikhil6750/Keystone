"""Workflow orchestration engine.

`state_machine.py` implements state-transition validation. `workflow_engine.py`
implements synchronous, sequential step execution against an `ExecutorRegistry`
(`registry.py`), threading an `ExecutionContext` (`context.py`) through each
step via the `AgentExecutor` contract (`executor.py`). It checks a per-agent-type
circuit breaker before every call and retries a `retryable` `StepExecutionError`
while attempts remain and the circuit permits it (bounded exponential backoff
via `app.resilience.retry.RetryPolicy`); otherwise it persists the failure and
stops, exactly as in Phase 2. `exceptions.py` defines `WorkflowNotFoundError`
and `InvalidWorkflowStateError`. Saga-style compensation is not yet implemented.
"""
