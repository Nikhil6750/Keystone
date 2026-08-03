"""Centralized application settings, read from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.adapters.types import CLIProfile, create_cli_profile


class Settings(BaseSettings):
    """Application configuration.

    Values are read from environment variables and, for local development,
    from a `.env` file (see `.env.example` for the supported keys). Phase 3
    settings all use an explicit `KEYSTONE_` prefix (see each field's
    `validation_alias`); existing Phase 1/2 variables keep their original,
    unprefixed names for backward compatibility.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    app_name: str = "keystone-backend"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./keystone.db"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Agent execution defaults ---
    agent_default_timeout_seconds: float = Field(
        default=60.0, validation_alias="KEYSTONE_AGENT_DEFAULT_TIMEOUT_SECONDS"
    )
    agent_max_prompt_characters: int = Field(
        default=20000, validation_alias="KEYSTONE_AGENT_MAX_PROMPT_CHARACTERS"
    )
    agent_max_output_characters: int = Field(
        default=50000, validation_alias="KEYSTONE_AGENT_MAX_OUTPUT_CHARACTERS"
    )

    # --- Retry ---
    retry_base_delay_seconds: float = Field(
        default=0.5, validation_alias="KEYSTONE_RETRY_BASE_DELAY_SECONDS"
    )
    retry_max_delay_seconds: float = Field(
        default=5.0, validation_alias="KEYSTONE_RETRY_MAX_DELAY_SECONDS"
    )
    retry_jitter_ratio: float = Field(default=0.1, validation_alias="KEYSTONE_RETRY_JITTER_RATIO")

    # --- Circuit breaker ---
    circuit_breaker_failure_threshold: int = Field(
        default=3, validation_alias="KEYSTONE_CIRCUIT_BREAKER_FAILURE_THRESHOLD"
    )
    circuit_breaker_recovery_timeout_seconds: float = Field(
        default=30.0, validation_alias="KEYSTONE_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS"
    )

    # --- Claude Code ---
    # Verified locally: `claude --help` confirms `-p`/`--print` for non-interactive
    # output and `--output-format json` for a single JSON result; the prompt is a
    # trailing positional argument. Still disabled by default (opt-in).
    claude_code_enabled: bool = Field(
        default=False, validation_alias="KEYSTONE_CLAUDE_CODE_ENABLED"
    )
    claude_code_executable: str = Field(
        default="claude", validation_alias="KEYSTONE_CLAUDE_CODE_EXECUTABLE"
    )
    claude_code_arguments: list[str] = Field(
        default_factory=lambda: ["-p", "--output-format", "json", "{prompt}"],
        validation_alias="KEYSTONE_CLAUDE_CODE_ARGUMENTS",
    )
    claude_code_input_mode: str = Field(
        default="prompt_argument", validation_alias="KEYSTONE_CLAUDE_CODE_INPUT_MODE"
    )
    claude_code_output_mode: str = Field(
        default="json", validation_alias="KEYSTONE_CLAUDE_CODE_OUTPUT_MODE"
    )
    claude_code_timeout_seconds: float | None = Field(
        default=None, validation_alias="KEYSTONE_CLAUDE_CODE_TIMEOUT_SECONDS"
    )

    # --- Codex ---
    # Not verified locally (codex CLI not installed here): disabled by default
    # with no default arguments. Explicit configuration is required to enable it.
    codex_enabled: bool = Field(default=False, validation_alias="KEYSTONE_CODEX_ENABLED")
    codex_executable: str = Field(default="codex", validation_alias="KEYSTONE_CODEX_EXECUTABLE")
    codex_arguments: list[str] = Field(
        default_factory=list, validation_alias="KEYSTONE_CODEX_ARGUMENTS"
    )
    codex_input_mode: str = Field(default="stdin", validation_alias="KEYSTONE_CODEX_INPUT_MODE")
    codex_output_mode: str = Field(default="text", validation_alias="KEYSTONE_CODEX_OUTPUT_MODE")
    codex_timeout_seconds: float | None = Field(
        default=None, validation_alias="KEYSTONE_CODEX_TIMEOUT_SECONDS"
    )

    # --- Gemini ---
    # Not verified locally (gemini CLI not installed here): disabled by default
    # with no default arguments. Explicit configuration is required to enable it.
    gemini_enabled: bool = Field(default=False, validation_alias="KEYSTONE_GEMINI_ENABLED")
    gemini_executable: str = Field(default="gemini", validation_alias="KEYSTONE_GEMINI_EXECUTABLE")
    gemini_arguments: list[str] = Field(
        default_factory=list, validation_alias="KEYSTONE_GEMINI_ARGUMENTS"
    )
    gemini_input_mode: str = Field(default="stdin", validation_alias="KEYSTONE_GEMINI_INPUT_MODE")
    gemini_output_mode: str = Field(default="text", validation_alias="KEYSTONE_GEMINI_OUTPUT_MODE")
    gemini_timeout_seconds: float | None = Field(
        default=None, validation_alias="KEYSTONE_GEMINI_TIMEOUT_SECONDS"
    )

    # --- Demo ---
    demo_enabled: bool = Field(default=False, validation_alias="KEYSTONE_DEMO_ENABLED")

    # --- Compensation ---
    auto_compensate_on_failure: bool = Field(
        default=False, validation_alias="KEYSTONE_AUTO_COMPENSATE_ON_FAILURE"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, parsed from the comma-separated setting."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def _resolve_timeout(self, override: float | None) -> float:
        return override if override is not None else self.agent_default_timeout_seconds

    def claude_code_profile(self) -> CLIProfile:
        """Build and validate the Claude Code CLI profile. Raises `ValueError` if invalid."""
        return create_cli_profile(
            agent_type="claude_code",
            enabled=self.claude_code_enabled,
            executable=self.claude_code_executable,
            arguments=self.claude_code_arguments,
            input_mode=self.claude_code_input_mode,
            output_mode=self.claude_code_output_mode,
            timeout_seconds=self._resolve_timeout(self.claude_code_timeout_seconds),
            max_output_characters=self.agent_max_output_characters,
        )

    def codex_profile(self) -> CLIProfile:
        """Build and validate the Codex CLI profile. Raises `ValueError` if invalid."""
        return create_cli_profile(
            agent_type="codex",
            enabled=self.codex_enabled,
            executable=self.codex_executable,
            arguments=self.codex_arguments,
            input_mode=self.codex_input_mode,
            output_mode=self.codex_output_mode,
            timeout_seconds=self._resolve_timeout(self.codex_timeout_seconds),
            max_output_characters=self.agent_max_output_characters,
        )

    def gemini_profile(self) -> CLIProfile:
        """Build and validate the Gemini CLI profile. Raises `ValueError` if invalid."""
        return create_cli_profile(
            agent_type="gemini",
            enabled=self.gemini_enabled,
            executable=self.gemini_executable,
            arguments=self.gemini_arguments,
            input_mode=self.gemini_input_mode,
            output_mode=self.gemini_output_mode,
            timeout_seconds=self._resolve_timeout(self.gemini_timeout_seconds),
            max_output_characters=self.agent_max_output_characters,
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
