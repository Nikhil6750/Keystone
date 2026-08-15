"""Tests for `app.integrations.nemotron.config.NemotronConfig`."""

import pytest

from app.integrations.nemotron.config import (
    DEFAULT_API_KEY_ENV_VAR,
    DEFAULT_HOSTED_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_STREAM,
    NemotronConfig,
)


def test_hosted_defaults() -> None:
    config = NemotronConfig()
    assert config.base_url == DEFAULT_HOSTED_BASE_URL == "https://integrate.api.nvidia.com/v1"
    assert config.model == DEFAULT_MODEL == "nvidia/nemotron-3-ultra-550b-a55b"
    assert config.api_key_env_var == DEFAULT_API_KEY_ENV_VAR == "NVIDIA_API_KEY"
    assert config.timeout_seconds > 0
    assert config.max_output_tokens > 0
    assert config.max_response_body_bytes > 0


# --- Stage 8B.1 Part C: bounded low-latency defaults -----------------------


def test_reasoning_effort_defaults_to_none() -> None:
    config = NemotronConfig()
    assert config.reasoning_effort == DEFAULT_REASONING_EFFORT == "none"


def test_stream_defaults_to_false() -> None:
    config = NemotronConfig()
    assert config.stream is DEFAULT_STREAM is False


@pytest.mark.parametrize("effort", ["none", "medium", "high"])
def test_reasoning_effort_accepts_every_documented_value(effort: str) -> None:
    config = NemotronConfig(reasoning_effort=effort)  # type: ignore[arg-type]
    assert config.reasoning_effort == effort


def test_reasoning_effort_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="reasoning_effort"):
        NemotronConfig(reasoning_effort="ultra")  # type: ignore[arg-type]


def test_stream_is_configurable_to_true() -> None:
    """Configurable does not mean recommended -- no SSE handling exists
    anywhere in this adapter yet; see Stage 8B.1 Part C. This only proves
    the field itself is a normal, overridable config value."""
    config = NemotronConfig(stream=True)
    assert config.stream is True


def test_chat_completions_url_hosted_default() -> None:
    config = NemotronConfig()
    assert config.chat_completions_url == "https://integrate.api.nvidia.com/v1/chat/completions"


def test_self_hosted_url() -> None:
    config = NemotronConfig(base_url="http://localhost:8000/v1")
    assert config.chat_completions_url == "http://localhost:8000/v1/chat/completions"


def test_self_hosted_url_trailing_slash_stripped() -> None:
    config = NemotronConfig(base_url="http://localhost:8000/v1/")
    assert config.chat_completions_url == "http://localhost:8000/v1/chat/completions"


def test_self_hosted_auth_optional_none() -> None:
    """Self-hosted deployments commonly need no Bearer credential at all."""
    config = NemotronConfig(base_url="http://localhost:8000/v1", api_key_env_var=None)
    assert config.resolve_api_key() is None


def test_env_var_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake-test-value-not-a-real-secret")
    config = NemotronConfig()
    assert config.resolve_api_key() == "nvapi-fake-test-value-not-a-real-secret"


def test_env_var_configurable_to_a_different_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_CUSTOM_NEMOTRON_KEY", "custom-fake-value")
    config = NemotronConfig(api_key_env_var="MY_CUSTOM_NEMOTRON_KEY")
    assert config.resolve_api_key() == "custom-fake-value"


def test_env_var_unset_resolves_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    config = NemotronConfig()
    assert config.resolve_api_key() is None


def test_env_var_blank_resolves_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    config = NemotronConfig()
    assert config.resolve_api_key() is None


def test_no_automatic_ngc_api_key_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default config must never silently read NGC_API_KEY when
    NVIDIA_API_KEY is unset -- that fallback was removed from the certified
    Stage 8B0 spike probe script and must never reappear here."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NGC_API_KEY", "ngc-fake-value-should-not-be-used")
    config = NemotronConfig()
    assert config.resolve_api_key() is None


def test_ngc_api_key_usable_only_via_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NGC_API_KEY", "ngc-fake-value-explicit-opt-in")
    config = NemotronConfig(api_key_env_var="NGC_API_KEY")
    assert config.resolve_api_key() == "ngc-fake-value-explicit-opt-in"


def test_secret_does_not_appear_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_marker = "nvapi-super-secret-marker-should-never-leak-123456"
    monkeypatch.setenv("NVIDIA_API_KEY", secret_marker)
    config = NemotronConfig()
    assert secret_marker not in repr(config)
    assert secret_marker not in str(config)


def test_config_has_no_field_to_hold_a_resolved_secret() -> None:
    """`NemotronConfig` only ever stores the *name* of an environment
    variable, never a resolved value -- structural, not just behavioral."""
    field_names = {f for f in NemotronConfig.__dataclass_fields__}
    assert "api_key" not in field_names
    assert "api_key_value" not in field_names
    assert "secret" not in field_names
    assert "token" not in field_names


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": ""},
        {"base_url": "   "},
        {"model": ""},
        {"api_key_env_var": ""},
        {"timeout_seconds": 0},
        {"timeout_seconds": -1.0},
        {"max_output_tokens": 0},
        {"max_output_tokens": -5},
        {"max_response_body_bytes": 0},
        {"user_agent_product": ""},
    ],
)
def test_invalid_config_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        NemotronConfig(**kwargs)  # type: ignore[arg-type]


def test_config_is_frozen() -> None:
    config = NemotronConfig()
    with pytest.raises(AttributeError):
        config.model = "something-else"  # type: ignore[misc]
