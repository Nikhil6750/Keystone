#!/usr/bin/env python3
"""
NVIDIA Nemotron 3 Ultra Integration Probe (Spike)
Stage 8B0 Isolation Probe Script

Rules:
- Reads API key ONLY from environment variables (NVIDIA_API_KEY, NGC_API_KEY).
- NEVER prints or logs API keys.
- Uses safe, static trivial prompt.
- Explicit request timeout.
- Error response sanitization.
- Zero project data transmission.
"""

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL_ID = "nvidia/nemotron-3-ultra-550b-a55b"
TIMEOUT_SECONDS = 15.0


def sanitize_text(text: str, key_to_redact: str = "") -> str:
    """Sanitize output to ensure credentials are never leaked."""
    if not text:
        return ""
    if key_to_redact and len(key_to_redact) > 4:
        text = text.replace(key_to_redact, "[REDACTED_API_KEY]")
    # Redact potential Bearer tokens in headers
    import re
    text = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]+', 'Bearer [REDACTED]', text)
    text = re.sub(r'nvapi-[A-Za-z0-9_\-\.]+', 'nvapi-[REDACTED]', text)
    return text


def run_probe():
    api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("NGC_API_KEY")

    if not api_key:
        print("LIVE TEST NOT RUN -- NO CREDENTIAL")
        return 0

    base_url = os.getenv("NVIDIA_BASE_URL", DEFAULT_NVIDIA_BASE_URL).rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    model_id = os.getenv("NVIDIA_MODEL_ID", DEFAULT_MODEL_ID)

    print(f"Target Endpoint: {endpoint}")
    print(f"Model ID: {model_id}")
    print("Credential Status: Available (masked)")

    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": "Respond with JSON containing status ok."
            }
        ],
        "temperature": 0.1,
        "max_tokens": 64,
        "response_format": {"type": "json_object"}
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )

    try:
        import time
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            latency_ms = round((time.time() - start_time) * 1000, 2)
            res_body = response.read().decode("utf-8")
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
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        sanitized_msg = sanitize_text(f"HTTPError {e.code}: {e.reason} - {error_body}", api_key)
        print(f"LIVE TEST RESULT: FAILED (HTTP Error)")
        print(f"Sanitized Error: {sanitized_msg}")
        return 1
    except urllib.error.URLError as e:
        sanitized_msg = sanitize_text(f"URLError: {e.reason}", api_key)
        print(f"LIVE TEST RESULT: FAILED (URL/Network Error)")
        print(f"Sanitized Error: {sanitized_msg}")
        return 1
    except Exception as e:
        sanitized_msg = sanitize_text(f"Unexpected error: {type(e).__name__}: {str(e)}", api_key)
        print(f"LIVE TEST RESULT: FAILED (Unexpected Error)")
        print(f"Sanitized Error: {sanitized_msg}")
        return 1


if __name__ == "__main__":
    sys.exit(run_probe())
