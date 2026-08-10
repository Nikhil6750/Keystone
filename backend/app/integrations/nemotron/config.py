"""Immutable, typed configuration for the Nemotron Chat-Completions adapter.

**Never stores a secret value.** `NemotronConfig` holds only the *name* of
the environment variable to read (`api_key_env_var`), never the resolved
key itself -- there is structurally no field on this type an API key could
ever occupy, so the default `repr`/`str`/equality of a frozen dataclass is
already leak-safe with no custom override needed (see
`test_nemotron_config.py::test_repr_never_contains_a_resolved_secret_value`).
`resolve_api_key()` reads the environment fresh on every call rather than
caching the value anywhere on the instance.

**No automatic `NGC_API_KEY` fallback**, per the certified Stage 8B0 spike
(`docs/stage8/nemotron-integration-spike.md`, section 8): `NGC_API_KEY`
authorizes NGC registry / container / model-download access, not hosted
inference, and the two must never be silently interchangeable. An operator
who wants a different variable name -- including reusing `NGC_API_KEY` for
inference, if their deployment happens to do that -- sets `api_key_env_var`
explicitly; there is no fallback chain.

**Hosted and self-hosted are the same shape.** Self-hosted NIM normally
needs no Bearer credential for localhost inference unless the deployer
explicitly adds authentication (same spike, section 8) -- setting
`api_key_env_var=None` (or pointing it at an unset environment variable)
naturally produces an unauthenticated request, which is exactly what a
default self-hosted deployment expects.
"""

import os
from dataclasses import dataclass
from typing import Literal

DEFAULT_HOSTED_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_API_KEY_ENV_VAR = "NVIDIA_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_OUTPUT_TOKENS = 1024

# Centrally-defined response-size bound (Stage 8B rule 12): enforced by
# `transport.py` while streaming the response body, before any JSON
# parsing is attempted.
MAX_RESPONSE_BODY_BYTES = 1_000_000

# Stage 8B.1 Part C: bounded low-latency defaults for Keystone Manager
# structured planning. Neither field was previously sent explicitly by
# this adapter -- a certified live diagnostic observed ~20.4s for one call
# with the provider left to its own defaults. "none"/`False` are the
# minimum-latency settings; a caller with a genuine need for deeper
# reasoning can opt into "medium"/"high" explicitly via `NemotronConfig`,
# never by editing this adapter's code.
ReasoningEffort = Literal["none", "medium", "high"]
DEFAULT_REASONING_EFFORT: ReasoningEffort = "none"
DEFAULT_STREAM = False
_VALID_REASONING_EFFORTS: frozenset[str] = frozenset({"none", "medium", "high"})


@dataclass(frozen=True)
class NemotronConfig:
    """Configuration for one `NemotronManagerModel`. Frozen and plain (not
    a Pydantic model) -- matches this codebase's convention for internal
    engine-side policy objects (`ManagerOrchestrationPolicy`,
    `RecoveryPolicy`, `AdaptiveRetrievalPolicy`), as distinct from the
    Pydantic contracts that cross a serialization boundary."""

    base_url: str = DEFAULT_HOSTED_BASE_URL
    model: str = DEFAULT_MODEL
    api_key_env_var: str | None = DEFAULT_API_KEY_ENV_VAR
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    max_response_body_bytes: int = MAX_RESPONSE_BODY_BYTES
    # `response_format={"type": "json_object"}` is capability-gated on the
    # hosted endpoint (spike doc, section 5.1) -- optional and off by
    # default. The adapter's mandatory validation path (final content ->
    # JSON decode -> Pydantic ManagerResponse -> ManagerProposalValidator)
    # does not depend on this being honored by the provider either way.
    request_json_mode: bool = False
    # A safe, non-fabricated identifier only -- see `transport.py`'s
    # `build_user_agent()` for how this composes with the project's actual
    # installed version (never a hardcoded/guessed version string).
    user_agent_product: str = "Keystone-Nemotron-Adapter"
    # Bounded low-latency defaults -- see the module-level comment above.
    # Configurable per `NemotronConfig` instance, never scattered as a
    # provider-specific literal inside `serialization.py`/`adapter.py`.
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT
    stream: bool = DEFAULT_STREAM

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("base_url must not be blank")
        if not self.model.strip():
            raise ValueError("model must not be blank")
        if self.api_key_env_var is not None and not self.api_key_env_var.strip():
            raise ValueError("api_key_env_var must not be blank when provided")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.max_response_body_bytes <= 0:
            raise ValueError("max_response_body_bytes must be positive")
        if not self.user_agent_product.strip():
            raise ValueError("user_agent_product must not be blank")
        if self.reasoning_effort not in _VALID_REASONING_EFFORTS:
            raise ValueError(
                "reasoning_effort must be one of "
                f"{sorted(_VALID_REASONING_EFFORTS)}, got {self.reasoning_effort!r}"
            )

    @property
    def chat_completions_url(self) -> str:
        """`base_url` with exactly one trailing slash stripped, plus
        `/chat/completions` -- works identically for the hosted default and
        for a self-hosted `http://localhost:<port>/v1` base."""
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def resolve_api_key(self) -> str | None:
        """Read the configured environment variable *now* and return its
        value, or `None` if `api_key_env_var` is `None` or the variable is
        unset/empty. Never caches the result on `self` -- there is no field
        for it to occupy. Never logs or prints the value; callers must
        uphold the same discipline (see `adapter.py`/`transport.py`)."""
        if self.api_key_env_var is None:
            return None
        value = os.environ.get(self.api_key_env_var)
        return value if value else None


__all__ = [
    "DEFAULT_API_KEY_ENV_VAR",
    "DEFAULT_HOSTED_BASE_URL",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_REASONING_EFFORT",
    "DEFAULT_STREAM",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_RESPONSE_BODY_BYTES",
    "NemotronConfig",
    "ReasoningEffort",
]
