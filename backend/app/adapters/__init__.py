"""Local CLI agent adapters.

`types.py` defines the canonical agent types and `CLIProfile` configuration;
`exceptions.py` the typed adapter errors (each a `StepExecutionError` with a
stable code and retryability); `process_runner.py` the safe, shell-free
subprocess execution boundary; `prompt_builder.py` the shared deterministic
prompt construction; `local_cli.py` the shared `AgentExecutor` implementation
subclassed by `claude_code.py`, `codex.py`, and `gemini.py`; `demo.py` a
no-subprocess, explicitly-opt-in demonstration adapter; and `factory.py` the
settings-driven registration composed during application startup.
"""
