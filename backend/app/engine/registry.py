"""In-process registry mapping agent_type to AgentExecutor implementations.

Not a module-level singleton: create one instance per application (via lifespan
state) or per test, and pass it explicitly wherever an executor lookup is needed.
"""

from app.engine.executor import AgentExecutor


class ExecutorNotRegisteredError(Exception):
    """Raised when no executor is registered for the requested agent type."""

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type
        super().__init__(f"no executor registered for agent type '{agent_type}'")


class ExecutorRegistry:
    """Maps normalized agent_type strings to `AgentExecutor` implementations."""

    def __init__(self) -> None:
        self._executors: dict[str, AgentExecutor] = {}

    @staticmethod
    def _normalize(agent_type: str) -> str:
        normalized = agent_type.strip().lower()
        if not normalized:
            raise ValueError("agent_type must not be blank")
        return normalized

    def register(self, agent_type: str, executor: AgentExecutor, *, replace: bool = False) -> None:
        """Register an executor for `agent_type`.

        Raises `ValueError` if an executor is already registered and `replace`
        is not explicitly set to `True`.
        """
        normalized = self._normalize(agent_type)
        if normalized in self._executors and not replace:
            raise ValueError(
                f"an executor is already registered for agent type '{normalized}'; "
                "pass replace=True to replace it deliberately"
            )
        self._executors[normalized] = executor

    def get(self, agent_type: str) -> AgentExecutor:
        """Retrieve the executor registered for `agent_type`.

        Raises `ExecutorNotRegisteredError` if none is registered.
        """
        normalized = self._normalize(agent_type)
        executor = self._executors.get(normalized)
        if executor is None:
            raise ExecutorNotRegisteredError(normalized)
        return executor
