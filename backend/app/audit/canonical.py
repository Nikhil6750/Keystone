"""Deterministic canonical JSON serialization for audit-hash inputs.

Hashing is only tamper-evident if two logically-identical envelopes always
serialize to exactly the same bytes. This module is the single place that
serialization happens for hashing purposes.
"""

import json
from typing import Any

_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))


def _validate_json_compatible(value: Any) -> None:
    """Raise `TypeError` if `value` contains anything outside plain JSON types.

    Deliberately stricter than `json.dumps`'s own default behavior: rejects
    anything that would silently fall back to a non-deterministic or
    non-JSON representation (e.g. a custom object, `datetime`, or `set`).
    """
    if isinstance(value, _JSON_SCALAR_TYPES):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_compatible(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"canonical JSON object keys must be strings, got {type(key)!r}")
            _validate_json_compatible(item)
        return
    raise TypeError(f"value of type {type(value)!r} is not JSON-compatible for canonical hashing")


def canonical_json(value: Any) -> str:
    """Serialize `value` to a deterministic, UTF-8-safe canonical JSON string.

    Object keys are sorted, separators are compact, and only plain JSON types
    (dict/list/str/int/float/bool/None) are accepted — never Python `repr`,
    never a memory address, never a locale- or timezone-dependent format.
    Callers must pre-format timestamps as stable ISO-8601 UTC strings.
    """
    _validate_json_compatible(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
