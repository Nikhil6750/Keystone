"""Tests for deterministic canonical JSON serialization used by audit hashing."""

import pytest

from app.audit.canonical import canonical_json


def test_object_keys_are_sorted() -> None:
    result = canonical_json({"b": 1, "a": 2, "c": 3})

    assert result == '{"a":2,"b":1,"c":3}'


def test_separators_are_compact_with_no_whitespace() -> None:
    result = canonical_json({"a": 1, "b": [1, 2, 3]})

    assert " " not in result


def test_serialization_is_deterministic_regardless_of_insertion_order() -> None:
    first = canonical_json({"a": 1, "b": 2, "c": 3})
    second = canonical_json({"c": 3, "b": 2, "a": 1})

    assert first == second


def test_nested_structures_are_serialized_consistently() -> None:
    value = {"outer": {"z": 1, "a": [3, 2, {"y": 1, "x": 2}]}}

    result = canonical_json(value)

    assert result == '{"outer":{"a":[3,2,{"x":2,"y":1}],"z":1}}'


def test_non_ascii_characters_are_preserved_not_escaped() -> None:
    result = canonical_json({"name": "café"})

    assert "café" in result
    assert "\\u00e9" not in result


def test_scalar_types_round_trip() -> None:
    value = {"s": "text", "i": 1, "f": 1.5, "b": True, "n": None}

    result = canonical_json(value)

    assert result == '{"b":true,"f":1.5,"i":1,"n":null,"s":"text"}'


def test_rejects_non_json_compatible_values() -> None:
    with pytest.raises(TypeError):
        canonical_json({"bad": {1, 2, 3}})


def test_rejects_non_string_dict_keys() -> None:
    with pytest.raises(TypeError):
        canonical_json({1: "value"})  # type: ignore[dict-item]
