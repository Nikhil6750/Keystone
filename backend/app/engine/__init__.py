"""Workflow orchestration engine.

`state_machine.py` implements state-transition validation. `workflow_engine.py`
implements synchronous, sequential step execution against an `ExecutorRegistry`
(`registry.py`), threading an `ExecutionContext` (`context.py`) through each
step via the `AgentExecutor` contract (`executor.py`). Retries, circuit
breakers, and saga-style compensation are not yet implemented.
"""
