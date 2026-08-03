# Live local provider connectors (Phase 6A.1)

This document describes how Keystone connects to real, locally installed coding-agent
CLIs — Claude Code, Codex, and Google Antigravity — in addition to the built-in `demo`
agent and the reserved-but-unconfigured Gemini CLI slot.

**Keystone does not receive provider passwords, browser cookies, OAuth refresh tokens,
or API keys. It invokes locally installed provider CLIs that are already authenticated
under the backend operating-system user.**

## Supported agents and canonical IDs

| Canonical `agent_type` | Display name | Executable | Status in this environment |
| --- | --- | --- | --- |
| `claude_code` | Claude Code | `claude` | Installed and authenticated — live-verified |
| `codex` | OpenAI Codex | `codex` | Not installed here — adapter is modeled/untested |
| `antigravity` | Google Antigravity | `agy` | Not installed here — adapter is modeled/untested |
| `gemini` | Gemini CLI | `gemini` | Reserved, unconfigured, out of scope for this phase |
| `demo` | Demo Agent | — (no subprocess) | Deterministic local stand-in, no real provider |

`gemini` and `antigravity` are **permanently separate canonical values**. Google
Antigravity is a distinct local coding agent from Google's standalone Gemini CLI; its
executable is `agy`, never `gemini`, and it is never registered, executed, or labeled
as "Gemini CLI" anywhere in the backend or frontend.

## Authentication model

Keystone never installs a provider CLI and never drives an interactive login. Every
adapter assumes the CLI is **already installed and authenticated separately, by the
operator, under the same Windows user account that runs the Keystone backend process**
(subscription-based login, managed entirely by that CLI). If a CLI is missing or not
authenticated, Keystone reports that state honestly — it never attempts to install the
CLI, launch a browser login, or collect a credential on its behalf.

Local login commands (run these yourself, in a terminal, on the machine running the
backend — Keystone never runs them for you):

- Claude Code: `claude auth login`
- Codex: `codex login`
- Google Antigravity: run `agy` and complete the official browser sign-in it opens

Keystone never reads Windows Credential Manager, browser storage, OAuth tokens,
credential files, keyring data, cookies, or refresh/access tokens. It never invokes a
provider's `/logout`. Where a provider CLI's own status command returns account details
(for example, `claude auth status` returns `loggedIn`, `email`, `organizationId`,
`organizationName`, and `subscriptionType`), Keystone extracts **only** the minimal
boolean it needs (`loggedIn`) — the rest is never read, logged, or exposed.

## Three independent connection statuses

A single boolean cannot honestly represent "is this agent usable?" — Keystone tracks
three independent fields per agent type (`backend/app/adapters/connection.py`):

- **`installation_status`** (`installed` / `not_installed` / `unknown`) — whether the
  configured executable resolves on `PATH`.
- **`authentication_status`** (`authenticated` / `unauthenticated` / `unknown` /
  `error`) — from the provider's own safe status command, or inferred from a
  successful verification call. Never inferred merely from the executable's presence.
- **`connection_status`** (`connected` / `unavailable` / `verification_failed` /
  `verification_required` / `disabled`) — `connected` means a safe headless
  verification call **actually succeeded recently** (within the connection-cache
  window); `installed` is never labeled `connected`.

## Safe connection verification

`POST /api/v1/agents/{agent_type}/verify` runs one harmless, backend-owned headless
prompt against the provider CLI:

> Reply with exactly `KEYSTONE_{AGENT_TYPE}_VERIFY_{random}`. Do not read files,
> inspect the repository, invoke tools, execute commands, access the network, or
> modify anything.

The token is freshly generated per call (`new_verification_token`) so a stale or cached
provider response can never be mistaken for a fresh success. The endpoint takes no
request body — nothing from the caller is ever forwarded to a provider process. An
in-process lock (`AgentConnectionCache.try_begin_verification`) rejects a duplicate
concurrent verification of the same agent type with `409 AGENT_VERIFICATION_IN_PROGRESS`
rather than launching two overlapping CLI processes. Results are cached briefly
(`KEYSTONE_AGENT_CONNECTION_CACHE_SECONDS`, default 60s) and reflected in subsequent
`GET /api/v1/agents` calls until the cache expires — `GET /agents` itself never
triggers a live verification as a side effect.

## Headless execution and structured output parsing

Every local-CLI adapter (`backend/app/adapters/local_cli.py` and its subclasses) shares
one process-invocation path (`_run_process`) built on the existing Phase 3
`SubprocessRunner` security boundary, then hands the raw result to a provider-specific
`_build_result` for output parsing:

- **Claude Code** (`claude_code.py`): parses the real, verified JSON envelope
  `{"type", "subtype", "is_error", "result", "session_id", "duration_ms"}` returned by
  `claude -p ... --output-format json`.
- **Codex** (`codex.py`): parses Codex's documented `exec --json` JSONL event stream —
  one JSON object per line, skipping malformed lines rather than failing outright —
  and extracts the final `agent_message`/`assistant_message` item's text.
- **Google Antigravity** (`antigravity.py`): parses a JSON object result envelope,
  checking `is_error`/`error` first, then the first present of several plausible
  content keys (`result`, `content`, `text`, `output`, `response`, `message`).

## Timeout and error handling

- A hard `timeout_seconds` per provider terminates a runaway process; exceeding it
  raises `AgentTimeoutError` (retryable, per existing Phase 3 policy).
- `max_output_characters` caps how much stdout/stderr is read from the process.
- stderr is bounded and sanitized before it is ever persisted or logged — never
  exposed to the frontend in full.
- A shared, keyword-based classifier (`error_classification.py`) recognizes
  authentication-failure, usage-limit, and permission/approval-required wording in a
  CLI's own error text and raises the matching **non-retryable** exception
  (`AgentAuthenticationError`, `AgentUsageLimitError`, `AgentPermissionError`). This is
  explicitly **best-effort and heuristic, not an exhaustive verified mapping** — Codex's
  and Antigravity's real failure-mode wording could not be observed in this environment
  since neither CLI is installed here.
- These three exceptions integrate with the *existing* Phase 2/3 engine retry and
  circuit-breaker machinery with zero engine changes: an authentication failure, a
  usage-limit exhaustion, or a permission/approval requirement is never automatically
  retried, since all three need human action, not another attempt.

## Workspace restrictions

`backend/app/adapters/workspace.py` provides `resolve_workspace_directory`, a
path-traversal-safe validator for a future feature that would let a trusted caller
confine an agent's working directory. **It is not yet wired into execution** — no
workflow input can specify a working directory today, so every adapter call still runs
in the isolated temporary directory the Phase 3 `SubprocessRunner` already creates per
call, never the real Keystone repository.

## Environment configuration

See `backend/.env.example` for the full, commented list. Nothing provider-specific is
ever a secret — every setting here is non-secret configuration (executable name,
argument list, timeouts):

- `KEYSTONE_CLAUDE_CODE_ENABLED` / `_EXECUTABLE` / `_ARGUMENTS` / `_INPUT_MODE` /
  `_OUTPUT_MODE` / `_TIMEOUT_SECONDS`
- `KEYSTONE_CODEX_ENABLED` / `_EXECUTABLE` / `_ARGUMENTS` / `_INPUT_MODE` /
  `_OUTPUT_MODE` / `_TIMEOUT_SECONDS`
- `KEYSTONE_ANTIGRAVITY_ENABLED` / `_EXECUTABLE` / `_ARGUMENTS` / `_INPUT_MODE` /
  `_OUTPUT_MODE` / `_TIMEOUT_SECONDS`
- `KEYSTONE_GEMINI_ENABLED` / `_EXECUTABLE` / `_ARGUMENTS` / `_INPUT_MODE` /
  `_OUTPUT_MODE` / `_TIMEOUT_SECONDS` (reserved, unconfigured)
- `KEYSTONE_AGENT_WORKSPACE_ROOT` — the workspace-validator's confinement root
  (not yet load-bearing; see above)
- `KEYSTONE_AGENT_CONNECTION_CACHE_SECONDS` — the verify-result cache TTL

All three real providers are **disabled by default** — enabling one requires the
operator to explicitly opt in after confirming their own local CLI is installed and
authenticated.

## Real-agent smoke tests performed in this environment

Only `claude` (Claude Code, v2.1.154) was genuinely installed and authenticated in the
environment this phase was built and verified in; `codex` and `agy` were confirmed
absent via both `Get-Command` (PowerShell) and `which` (Bash), returning nothing for
either. Per this phase's explicit instruction, a provider that cannot run headlessly
here is reported as a blocker — never faked as a success.

**Direct CLI smoke test**: `claude -p "Reply with exactly KEYSTONE_CLAUDE_CONNECTED. Do
not read files, inspect the repository, invoke tools, execute commands, access the
network, or modify anything." --output-format json` returned a genuine JSON envelope
with `"result":"KEYSTONE_CLAUDE_CONNECTED"` and `"is_error":false`.

**Live Keystone workflow smoke test**: with a disposable SQLite database and all three
real providers enabled, `GET /agents` correctly showed `claude_code` installed and
registered, `codex`/`antigravity` honestly `not_installed`/`unavailable`;
`POST /agents/claude_code/verify` returned `connected` / `authenticated` / version
`2.1.154 (Claude Code)`; a disposable one-step `claude_code` workflow
(`max_attempts=1`) succeeded with output content exactly `KEYSTONE_CLAUDE_CODE_WORKFLOW_OK`,
a valid 7-event audit chain, complete provenance, and a `closed` circuit breaker with
zero failures. The equivalent `codex` and `antigravity` workflows both honestly
returned `503 AGENT_EXECUTOR_NOT_REGISTERED` — never faked as a success. The
disposable database was deleted afterward; `git status --short` confirmed no
tracked-file changes resulted from the live tests.

This live verification is what caught the Windows `.cmd`-shim argument-mangling bug
described in `docs/backend-build-plan.md`'s Phase 6A.1 entry: the *first* attempt at
this same workflow failed with Claude Code replying "No JSON context was included in
your message," which led to switching Claude Code's (and Antigravity's) default
`input_mode` to `stdin`. The workflow above is the result *after* that fix, re-run and
confirmed successful.

## Known limitations

- **Codex and Google Antigravity adapters are modeled, not live-verified.** Their JSON/
  JSONL parsing and error classification are built from each provider's publicly
  documented conventions (Codex's `exec --json` event stream; the shared local-CLI JSON
  envelope convention for Antigravity), not from a captured real response, because
  neither CLI is installed in this environment. Enabling either in a different
  environment should be preceded by an operator's own `--help`/manual verification that
  the configured arguments still match their installed CLI version.
- The workspace-root validator exists but is not wired into execution — no workflow can
  select a working directory yet.
- Connection state is cached in-process only; it does not survive an application
  restart and is not shared across multiple backend instances.
- This phase adds no task decomposition, automatic agent selection, manager-agent
  routing, online agent marketplace, frontend-driven agent installation, MCP, A2A, RAG,
  or parallel/long-running background execution. See `docs/backend-build-plan.md`'s
  Phase 6A.2/Phase 6B entries for what remains future work.
