"""Tests for the in-process compensation-handler registry."""

from typing import Any

import pytest

from app.engine.compensation_context import CompensationRequest
from app.engine.compensation_exceptions import CompensationHandlerNotRegisteredError
from app.engine.compensation_registry import CompensationRegistry


class _StubHandler:
    def compensate(self, request: CompensationRequest) -> dict[str, Any]:
        return {}


def test_register_and_retrieve_handler_succeeds() -> None:
    registry = CompensationRegistry()
    handler = _StubHandler()

    registry.register("demo.undo", handler)

    assert registry.get("demo.undo") is handler


def test_blank_handler_name_is_rejected() -> None:
    registry = CompensationRegistry()
    with pytest.raises(ValueError, match="blank"):
        registry.register("   ", _StubHandler())


def test_duplicate_registration_is_rejected_by_default() -> None:
    registry = CompensationRegistry()
    registry.register("demo.undo", _StubHandler())

    with pytest.raises(ValueError, match="already registered"):
        registry.register("demo.undo", _StubHandler())


def test_explicit_replacement_works_when_requested() -> None:
    registry = CompensationRegistry()
    first = _StubHandler()
    second = _StubHandler()
    registry.register("demo.undo", first)

    registry.register("demo.undo", second, replace=True)

    assert registry.get("demo.undo") is second


def test_missing_handler_raises_focused_exception() -> None:
    registry = CompensationRegistry()
    with pytest.raises(CompensationHandlerNotRegisteredError):
        registry.get("unknown.handler")


def test_separate_registries_do_not_share_state() -> None:
    registry_a = CompensationRegistry()
    registry_b = CompensationRegistry()
    registry_a.register("demo.undo", _StubHandler())

    assert registry_a.get("demo.undo") is not None
    with pytest.raises(CompensationHandlerNotRegisteredError):
        registry_b.get("demo.undo")
