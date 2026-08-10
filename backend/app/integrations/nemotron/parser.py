"""Parses an NVIDIA OpenAI-compatible chat-completions HTTP response body
into a validated Stage 8A `ManagerResponse`.

**No reasoning/thinking persistence (Stage 8B rule 16).** `reasoning_content`,
any `<think>...</think>`-tagged text, or any other hidden-reasoning-shaped
field on the response is never read into a local variable beyond the
`dict.get` calls that skip past it -- it is never copied into the returned
`ManagerResponse`, never included in a raised exception's message, and
never logged anywhere in this module.

**No tool-call execution (Stage 8B rule 15).** A non-empty `tool_calls`
list on `choices[0].message` is treated as a malformed/unusable response
shape (`NemotronResponseError`) rather than something this module attempts
to execute or silently ignore-and-continue -- Stage 8B never runs a tool
loop, and a response that expected one to run is not the structured
proposal Stage 8A's `ManagerModel` protocol expects.

**No permissive JSON coercion (Stage 8B rule 9).** Strict `json.loads`
first; the *only* fallback is stripping a single ```` ```json ... ``` ````
fenced block that wraps the *entire* content with nothing else outside it.
Any other shape -- truncated JSON, prose plus embedded JSON, multiple
fenced blocks -- fails closed with `NemotronResponseError`. There is no
broader "JSON repair" behavior anywhere in this module.
"""

import json
import re
from typing import Any

from app.engine.manager.models import ManagerResponse
from app.engine.manager.protocol import parse_manager_response
from app.integrations.nemotron.errors import NemotronResponseError

_FENCED_JSON_RE = re.compile(r"\A```(?:json)?\s*\n(.*?)\n```\s*\Z", re.DOTALL)


def extract_final_content(payload: dict[str, Any]) -> str:
    """Extract `choices[0].message.content` from a chat-completions-shaped
    `payload`.

    Rejects (raises `NemotronResponseError`) anything that is not exactly
    this shape: missing/empty `choices`, a non-object `choices[0]` or
    `choices[0].message`, a message carrying non-empty `tool_calls`, or
    `content` that is missing, non-string, or blank. Never reads or returns
    `reasoning_content` or any think-tagged content.
    """
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise NemotronResponseError("provider response is missing 'choices'")

    first = choices[0]
    if not isinstance(first, dict):
        raise NemotronResponseError("provider response 'choices[0]' is not an object")

    message = first.get("message")
    if not isinstance(message, dict):
        raise NemotronResponseError("provider response 'choices[0].message' is not an object")

    tool_calls = message.get("tool_calls")
    if tool_calls:
        raise NemotronResponseError(
            "provider response included unexpected tool_calls; Stage 8B does not execute tools"
        )

    content = message.get("content")
    if not isinstance(content, str):
        raise NemotronResponseError("provider response content is missing or not a string")
    if not content.strip():
        raise NemotronResponseError("provider response content is empty")

    return content


def _strip_fenced_json(text: str) -> str | None:
    """If `text` (already stripped) is a single ```` ```json ... ``` ````
    fenced block wrapping the entire string, return the inner text.
    Otherwise return `None` -- this is the only extraction this module
    performs; every other shape is left for the caller to reject."""
    match = _FENCED_JSON_RE.match(text)
    return match.group(1) if match else None


def decode_json_object(content: str) -> dict[str, Any]:
    """Strict JSON decode of `content`, with one narrow fallback (a single
    fenced ```` ```json ```` block). Fails closed with `NemotronResponseError`
    for anything else, including a JSON value that decodes but is not an
    object."""
    candidate = content.strip()
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError:
        fenced = _strip_fenced_json(candidate)
        if fenced is None:
            raise NemotronResponseError("provider response content is not valid JSON") from None
        try:
            decoded = json.loads(fenced)
        except json.JSONDecodeError as exc:
            raise NemotronResponseError(
                "provider response content is not valid JSON (including after "
                "fenced-code-block extraction)"
            ) from exc

    if not isinstance(decoded, dict):
        raise NemotronResponseError("provider response JSON is not an object")
    return decoded


def parse_chat_completion_to_manager_response(payload: dict[str, Any]) -> ManagerResponse:
    """Full pipeline: chat-completions payload -> final content only ->
    strict JSON decode (narrow fenced-code fallback) -> Pydantic
    `ManagerResponse` (Stage 8A's `parse_manager_response`, which raises
    `ManagerInvalidResponseError` -- not this module's `NemotronResponseError`
    -- on a schema violation). This is the only place Stage 8B constructs a
    `ManagerResponse`.
    """
    content = extract_final_content(payload)
    decoded = decode_json_object(content)
    return parse_manager_response(decoded)


__all__ = [
    "decode_json_object",
    "extract_final_content",
    "parse_chat_completion_to_manager_response",
]
