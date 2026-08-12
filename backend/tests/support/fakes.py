"""Test-only fakes for resilience primitives and process execution. Never used by app/."""

from dataclasses import dataclass, field

from app.adapters.process_runner import ProcessResult


class FakeSleeper:
    """Records requested delays without actually sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeClock:
    """A manually advanceable monotonic clock for deterministic circuit-breaker tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@dataclass
class FakeProcessRunner:
    """A `ProcessRunner` double that never launches a real process.

    Set `result` to succeed, or `error` to raise it on the next call(s).
    """

    result: ProcessResult | None = None
    error: Exception | None = None
    calls: list[tuple[str, list[str]]] = field(default_factory=list)

    def run(
        self,
        executable: str,
        arguments: list[str],
        *,
        stdin_text: str | None,
        timeout_seconds: float,
        max_output_characters: int,
        env_overrides: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ProcessResult:
        self.calls.append((executable, list(arguments)))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("FakeProcessRunner.result was not configured")
        return self.result
