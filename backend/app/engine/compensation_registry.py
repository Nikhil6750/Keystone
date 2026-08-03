"""In-process registry mapping compensation handler names to `CompensationExecutor` implementations.

Not a module-level singleton: create one instance per application (via
lifespan state) or per test, and pass it explicitly wherever a handler lookup
is needed.
"""

from app.engine.compensation_exceptions import CompensationHandlerNotRegisteredError
from app.engine.compensation_executor import CompensationExecutor


class CompensationRegistry:
    """Maps normalized handler-name strings to `CompensationExecutor` implementations."""

    def __init__(self) -> None:
        self._handlers: dict[str, CompensationExecutor] = {}

    @staticmethod
    def _normalize(handler_name: str) -> str:
        normalized = handler_name.strip().lower()
        if not normalized:
            raise ValueError("handler_name must not be blank")
        return normalized

    def register(
        self, handler_name: str, handler: CompensationExecutor, *, replace: bool = False
    ) -> None:
        """Register a handler for `handler_name`.

        Raises `ValueError` if a handler is already registered and `replace`
        is not explicitly set to `True`.
        """
        normalized = self._normalize(handler_name)
        if normalized in self._handlers and not replace:
            raise ValueError(
                f"a compensation handler is already registered for '{normalized}'; "
                "pass replace=True to replace it deliberately"
            )
        self._handlers[normalized] = handler

    def get(self, handler_name: str) -> CompensationExecutor:
        """Retrieve the handler registered for `handler_name`.

        Raises `CompensationHandlerNotRegisteredError` if none is registered.
        """
        normalized = self._normalize(handler_name)
        handler = self._handlers.get(normalized)
        if handler is None:
            raise CompensationHandlerNotRegisteredError(normalized)
        return handler
