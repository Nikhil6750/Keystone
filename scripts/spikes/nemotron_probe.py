#!/usr/bin/env python3
"""
NVIDIA Nemotron 3 Ultra Integration Probe (Spike)
Stage 8B0 Isolation Probe Script

Rules:
- Reads the API key ONLY from the environment variable named by
  NVIDIA_API_KEY_ENV_VAR (default: NVIDIA_API_KEY). There is deliberately
  no automatic fallback to NGC_API_KEY: that variable authorizes NGC
  registry / container / model-download access, not hosted inference, and
  the two must never be treated as interchangeable by default. An operator
  who wants to probe with a different variable name (including
  NGC_API_KEY, if their deployment happens to reuse it for inference) sets
  NVIDIA_API_KEY_ENV_VAR explicitly. See docs/stage8/nemotron-integration-spike.md
  section 8.
- NEVER prints or logs API keys.
- Uses a safe, static trivial prompt. Zero project data transmission.
- Explicit request timeout; bounded response body read.
- Sanitizes error output before printing.
- response_format={"type": "json_object"} requests JSON mode only -- it is
  not a guaranteed strict JSON-schema conformance mechanism, and hosted
  endpoint support for it is not confirmed by current NVIDIA hosted API
  documentation (capability-gated; see spike doc section 5.1). A real
  Stage 8B adapter must be able to fall back to prompt-constrained JSON
  without weakening downstream Pydantic/ManagerProposalValidator checks.
"""

import contextlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL_ID = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_API_KEY_ENV_VAR = "NVIDIA_API_KEY"
TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BODY_BYTES = 1_000_000


def sanitize_text(text: str, key_to_redact: str = "") -> str:
    """Sanitize output to ensure credentials are never leaked."""
    if not text:
        return ""
    if key_to_redact and len(key_to_redact) > 4:
        text = text.replace(key_to_redact, "[REDACTED_API_KEY]")
    # Redact potential Bearer tokens / NVIDIA API key shapes in headers or bodies.
    text = re.sub(r"Bearer\s+[A-Za-z0-9_\-.]+", "Bearer [REDACTED]", text)
    text = re.sub(r"nvapi-[A-Za-z0-9_\-.]+", "nvapi-[REDACTED]", text)
    return text


def _read_bounded(response: object, max_bytes: int) -> str:
    """Read at most `max_bytes` from a response-like object's `.read()`."""
    raw = response.read(max_bytes)  # type: ignore[attr-defined]
    return raw.decode("utf-8", errors="replace")


def run_probe() -> int:
    api_key_env_var = os.getenv("NVIDIA_API_KEY_ENV_VAR", DEFAULT_API_KEY_ENV_VAR)
    api_key = os.getenv(api_key_env_var)

    if not api_key:
        print("LIVE TEST NOT RUN -- NO CREDENTIAL")
        print(f"Credential Env Var Checked: {api_key_env_var}")
        return 0

    base_url = os.getenv("NVIDIA_BASE_URL", DEFAULT_NVIDIA_BASE_URL).rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    model_id = os.getenv("NVIDIA_MODEL_ID", DEFAULT_MODEL_ID)

    print(f"Target Endpoint: {endpoint}")
    print(f"Model ID: {model_id}")
    print(f"Credential Env Var: {api_key_env_var}")
    print("Credential Status: Available (masked)")

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Respond with JSON containing status ok."}],
        "temperature": 0.1,
        "max_tokens": 64,
        # JSON mode only -- see module docstring; not a schema guarantee, and
        # capability-gated on the hosted endpoint (spike doc section 5.1).
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            latency_ms = round((time.time() - start_time) * 1000, 2)
            res_body = _read_bounded(response, MAX_RESPONSE_BODY_BYTES)
            status_code = response.status

            print(f"HTTP Status: {status_code}")
            print(f"Latency: {latency_ms} ms")

            parsed = json.loads(res_body)
            choices = parsed.get("choices", [])
            usage = parsed.get("usage", {})

            print(f"Response Choices Count: {len(choices)}")
            if choices:
                msg_content = choices[0].get("message", {}).get("content", "")
                print(f"Response Content: {sanitize_text(msg_content, api_key)}")

            print(f"Usage Info: {json.dumps(usage)}")
            print("LIVE TEST RESULT: SUCCESS")
            return 0

    except urllib.error.HTTPError as e:
        error_body = ""
        with contextlib.suppress(OSError):
            error_body = _read_bounded(e, MAX_RESPONSE_BODY_BYTES)
        sanitized_msg = sanitize_text(f"HTTPError {e.code}: {e.reason} - {error_body}", api_key)
        print("LIVE TEST RESULT: FAILED (HTTP Error)")
        print(f"Sanitized Error: {sanitized_msg}")
        return 1
    except urllib.error.URLError as e:
        sanitized_msg = sanitize_text(f"URLError: {e.reason}", api_key)
        print("LIVE TEST RESULT: FAILED (URL/Network Error)")
        print(f"Sanitized Error: {sanitized_msg}")
        return 1
    except Exception as e:  # last-resort sanitized reporting for a spike probe
        sanitized_msg = sanitize_text(f"Unexpected error: {type(e).__name__}: {e}", api_key)
        print("LIVE TEST RESULT: FAILED (Unexpected Error)")
        print(f"Sanitized Error: {sanitized_msg}")
        return 1


if __name__ == "__main__":
    sys.exit(run_probe())
