# Stage 8B0: NVIDIA Nemotron 3 Ultra Provider Integration Spike Report

**Branch:** `feature/stage8b0-nemotron-spike`
**Base Commit:** `b08da8407909f1ba41bd9cf4536b0ead4c4a54f6` (`origin/feature/core-intelligence-vnext`)
**Date:** August 10, 2026
**Hardening pass date:** August 10, 2026
**Status:** READY FOR STAGE 8B IMPLEMENTATION

---

## 0. Hardening Pass Changelog

This revision corrects factual errors in the original spike report after a
second review against current NVIDIA primary documentation (see §14 for the
full source list). No Stage 8A/core files were touched; this is a
documentation/spike-script-only pass.

Corrected in this pass:

1. **Anthropic compatibility was wrongly reported as absent.** NVIDIA NIM
   for Nemotron 3 Ultra documents both an OpenAI-compatible surface
   (`/v1/chat/completions`, `/v1/completions`, `/v1/responses`) **and** an
   Anthropic-compatible surface (`/v1/messages`, `/v1/messages/count_tokens`).
   Keystone's recommendation to standardize on the OpenAI Chat Completions
   boundary anyway is now justified on its own engineering merits (§3), not
   on a false "Anthropic isn't supported" premise.
2. Hosted (`integrate.api.nvidia.com`) and self-hosted (NIM container)
   capabilities were being asserted interchangeably. §4 now separates them
   explicitly into a verified capability matrix, with a source and a
   VERIFIED / NOT VERIFIED / NOT APPLICABLE mark for every row.
3. "Structured output" was implied to mean guaranteed strict JSON-schema
   conformance. §5 corrects this to what is actually documented: JSON mode
   (`response_format={"type": "json_object"}` on the underlying
   OpenAI-compatible chat completions surface), not a schema-conformance
   guarantee, and marks hosted-endpoint support as capability-gated pending
   direct confirmation.
4. Tool calling's self-hosted server-configuration requirement
   (`--enable-auto-tool-choice`, `--tool-call-parser`, `--reasoning-parser`)
   was not previously documented, and was not distinguished from the
   hosted surface, where no equivalent customer-facing control is
   documented. §6 also records that Stage 8B does not need tool execution
   and this must not block implementation.
5. Reasoning-control field names are corrected to what NVIDIA's own
   documentation and reference pages actually show
   (`chat_template_kwargs.enable_thinking` / `low_effort` / `medium_effort`,
   plus a token-budget cap whose exact parameter name is backend-dependent)
   rather than an unverified `reasoning_effort` top-level field. §7 restates
   Keystone's never-persist/never-log rule against the corrected names.
6. `NVIDIA_API_KEY` (hosted inference credential) and `NGC_API_KEY`
   (NGC/container/model access credential) were being treated as
   interchangeable fallbacks. §8 separates them and recommends a
   configurable `api_key_env_var` instead of a silent fallback chain. The
   probe script (`scripts/spikes/nemotron_probe.py`) was updated to match.
7. The flat "requires 8x H100/H200/B200" hardware claim is replaced in §9
   with NVIDIA's actual, profile-dependent support-matrix range.

---

## 1. Executive Summary

This spike evaluates the integration architecture for **NVIDIA Nemotron 3
Ultra (550B-A55B)** into Keystone as part of Stage 8B. The primary
objective is to define a production-grade, provider-neutral adapter
architecture (`NemotronManagerModel`) that satisfies Stage 8A Manager
requirements without introducing tight coupling, proprietary SDK
dependencies, or credential leaks.

Strict isolation was maintained throughout this spike and this hardening
pass: **ZERO Stage 8A/core manager files were created or modified**, and
zero model weights or containers were downloaded locally.

---

## 2. Official Primary Sources & Technical Specs

| Attribute | Official Value / Specification | Source |
| :--- | :--- | :--- |
| **Model Identifier** | `nvidia/nemotron-3-ultra-550b-a55b` | [NVIDIA API Catalog model card](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/modelcard) |
| **Architecture** | Hybrid Mamba-Transformer (Nemotron-H) mixture-of-experts, text-only, reasoning-capable | [NIM Day-0 guide](https://docs.nvidia.com/nim/large-language-models/2.0.6/day-0/get-started-nemotron-3-ultra.html) |
| **Total / Active Parameters** | 550B total / up to 55B active per token | [NIM Day-0 guide](https://docs.nvidia.com/nim/large-language-models/2.0.6/day-0/get-started-nemotron-3-ultra.html) |
| **Context Limit** | 262,144 tokens (256K) native; extendable to 1,048,576 (1M) via explicit server configuration | [NIM Day-0 guide](https://docs.nvidia.com/nim/large-language-models/2.0.6/day-0/get-started-nemotron-3-ultra.html) |
| **Hosted API base** | `https://integrate.api.nvidia.com/v1` | [NVIDIA LLM API reference (hosted)](https://docs.api.nvidia.com/nim/reference/llm-apis) |
| **NIM API reference (self-hosted)** | Full endpoint list, incl. OpenAI- and Anthropic-compatible routes | [NIM LLM API Reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html) |
| **GPU support matrix** | Per-model, per-profile, per-precision GPU/TP/PP table | [NIM LLM Support Matrix](https://docs.nvidia.com/nim/large-language-models/latest/reference/support-matrix.html) |
| **Tool calling / MCP** | Server flags, MCP is client-side only | [Tool Calling and MCP Integration](https://docs.nvidia.com/nim/large-language-models/latest/advanced-use-cases/tool-calling-and-mcp.html) |
| **Anthropic-compatible Claude Code integration** | `/v1/messages` usage on self-hosted NIM | [Use Claude Code with NIM](https://docs.nvidia.com/nim/large-language-models/latest/ai-assistant-integrations/claude-code.html) |
| **Credential model** | `NVIDIA_API_KEY` (hosted inference) vs `NGC_API_KEY` (NGC/container access) | [NVIDIA RAG Blueprint — Get an API Key](https://docs.nvidia.com/rag/2.5.0/api-key.html) |
| **Weights & License** | OpenMDW License v1.1 | Hugging Face (`nvidia/Nemotron-3-Ultra-550B-A55B`) |

A NVIDIA developer/technical blog post, if referenced anywhere informally
during this spike, is supplementary color only — every capability claim in
§4 below is backed by one of the `docs.nvidia.com` / `docs.api.nvidia.com` /
`build.nvidia.com` URLs in this table, never a blog, OpenRouter listing, or
third-party host.

---

## 3. Protocol & API Interface Analysis

### 3.1 Hosted Endpoint & Authentication

* **Base URL:** `https://integrate.api.nvidia.com/v1`
* **Inference Endpoint:** `https://integrate.api.nvidia.com/v1/chat/completions`
* **Authentication Mechanism:** Standard HTTP Authorization header:
  ```http
  Authorization: Bearer <API_KEY>
  ```
* **Credential Variable:** See §8 — do not conflate the hosted inference
  credential with `NGC_API_KEY`.

### 3.2 Protocol Compatibility (corrected)

* **OpenAI Compatibility:** **YES.** Both the hosted API catalog and
  self-hosted NIM containers expose an OpenAI-compatible
  `/v1/chat/completions` surface; self-hosted NIM additionally documents
  `/v1/completions` and `/v1/responses`.
* **Anthropic Compatibility:** **YES — self-hosted NIM documents
  `/v1/messages` and `/v1/messages/count_tokens`.** This was previously
  reported as unsupported; that was incorrect. See §4 for exactly which of
  these routes are verified on the *hosted* surface specifically (fewer
  than on self-hosted NIM — see the matrix's NOT VERIFIED rows).
* **Streaming:** Server-Sent Events (`stream: true`) returning incremental
  `delta`-shaped JSON chunks, documented on both hosted and self-hosted
  OpenAI-compatible chat completions.

### 3.3 Why Keystone still standardizes on OpenAI Chat Completions

Even though Anthropic compatibility genuinely exists on NIM, Stage 8B's
`NemotronManagerModel` should still target `/v1/chat/completions` first:

1. **Simplest common hosted/NIM surface.** It is the one route confirmed
   present on *both* the hosted API catalog and every self-hosted NIM
   profile (§4) — `/v1/messages` is confirmed on self-hosted NIM only.
2. **Directly documented for `integrate.api.nvidia.com`.** The hosted API
   reference documents `/v1/chat/completions` explicitly; no equivalent
   hosted-specific `/v1/messages` documentation was found (§4).
3. **Keeps `ManagerModel` provider-neutral.** `app.engine.manager.protocol
   .ManagerModel` (Stage 8A, unmodified by this spike) already assumes a
   generic request/response shape — an OpenAI-style chat completions
   payload is the most widely reproducible shape to serialize into and
   parse out of without provider-specific message-block semantics.
4. **No need for an Anthropic SDK.** The OpenAI-compatible surface is a
   plain JSON-over-HTTP contract Keystone's existing/`httpx` dependency can
   speak directly (§10); an Anthropic-shaped integration would still need
   only HTTP, but picking the surface that is *also* the hosted-catalog
   default avoids maintaining two request-shaping code paths for one
   provider.
5. **Easier hosted/self-hosted endpoint swapping.** Because both delivery
   paths agree on `/v1/chat/completions`, `NemotronConfig.base_url` is the
   only thing that changes between hosted and self-hosted — the request/
   response shaping code stays identical.

---

## 4. Hosted vs. Self-Hosted Capability Matrix

Marked `VERIFIED` only when a `docs.nvidia.com` / `docs.api.nvidia.com` /
`build.nvidia.com` page was directly checked during this hardening pass and
explicitly documents the capability for the named surface. `NOT VERIFIED`
means no such page was found describing that capability for that specific
surface — this is **not** a claim that the capability is absent, only that
it is unconfirmed and must not be assumed by the Stage 8B adapter.
`NOT APPLICABLE` means the capability concept does not meaningfully apply
to that surface.

| Capability | NVIDIA hosted API (`integrate.api.nvidia.com`) | Self-hosted NIM container | Verified source |
| :--- | :--- | :--- | :--- |
| Chat completions (`/v1/chat/completions`) | **VERIFIED** | **VERIFIED** | [Hosted LLM API reference](https://docs.api.nvidia.com/nim/reference/llm-apis); [NIM LLM API reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html) |
| Text completions (`/v1/completions`) | NOT VERIFIED | **VERIFIED** | [NIM LLM API reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html) |
| Streaming (`stream: true`, SSE deltas) | **VERIFIED** | **VERIFIED** | Documented `curl`/Python streaming example against `integrate.api.nvidia.com/v1/chat/completions`; [NIM LLM API reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html) for self-hosted |
| Reasoning controls (`chat_template_kwargs`: `enable_thinking`/`low_effort`/`medium_effort`) | NOT VERIFIED | **VERIFIED** | [Nemotron 3 Ultra API reference](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-ultra-550b-a55b) (self-hosted `localhost:8000` examples) |
| JSON mode (`response_format={"type":"json_object"}`) | NOT VERIFIED (capability-gated) | NOT VERIFIED (capability-gated) | No `docs.nvidia.com`/`docs.api.nvidia.com` page found that enumerates `response_format` for this model on either surface during this pass; treat as capability-gated, not guaranteed, on both. See §5. |
| Tool calling (`tools`/`tool_choice` request fields) | NOT VERIFIED | **VERIFIED** (once server-configured — see next row) | [Tool Calling and MCP Integration](https://docs.nvidia.com/nim/large-language-models/latest/advanced-use-cases/tool-calling-and-mcp.html) |
| Server-side tool parser configuration (`--enable-auto-tool-choice`, `--tool-call-parser`, `--reasoning-parser`) | **NOT APPLICABLE** (no customer-facing server configuration exists for a fully managed hosted endpoint) | **VERIFIED** | [Tool Calling and MCP Integration](https://docs.nvidia.com/nim/large-language-models/latest/advanced-use-cases/tool-calling-and-mcp.html) |
| Anthropic Messages (`/v1/messages`) | NOT VERIFIED | **VERIFIED** | [NIM LLM API reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html); [Use Claude Code with NIM](https://docs.nvidia.com/nim/large-language-models/latest/ai-assistant-integrations/claude-code.html) (self-hosted only — this page makes no mention of `integrate.api.nvidia.com`) |
| Anthropic token counting (`/v1/messages/count_tokens`) | NOT VERIFIED | **VERIFIED** | [NIM LLM API reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html) |
| Responses API (`/v1/responses`) | NOT VERIFIED | **VERIFIED** | [NIM LLM API reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html) |
| Health endpoints (`/v1/health/live`, `/v1/health/ready`) | **NOT APPLICABLE** (hosted uptime is NVIDIA-operated; no customer-facing per-request health route documented) | **VERIFIED** | [NIM LLM API reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html) |

**Do not claim a hosted capability merely because self-hosted NIM supports
it** — every `NOT VERIFIED` cell above is a case where a capability is
confirmed for self-hosted NIM but no hosted-specific documentation was
found. Stage 8B's initial adapter targets only the row that is `VERIFIED`
on both surfaces (chat completions + streaming), consistent with §3.3.

---

## 5. Structured Output & Reasoning Traces

### 5.1 Structured Output Support (corrected)

NIM documents `response_format={"type": "json_object"}` on the
OpenAI-compatible chat completions surface as **JSON mode** — the model is
instructed to emit syntactically valid JSON. This is **not** documented
anywhere checked in this pass as a *guaranteed strict JSON-schema
conformance* mechanism (i.e. it does not promise the JSON will match a
caller-supplied schema, only that it will parse as JSON). Per §4, direct
hosted-endpoint documentation for this parameter was not found during this
pass, so Stage 8B must treat `response_format` support as **capability-gated**
on both surfaces rather than assumed.

#### Stage 8B path (mandatory shape, unchanged by this spike):

```
provider response
  -> extract final content only (never reasoning/thinking content, see 5.2)
  -> JSON parse
  -> Pydantic ManagerResponse            (app.engine.manager.models, Stage 8A)
  -> ManagerProposalValidator            (app.engine.manager.validation, Stage 8A)
```

The Stage 8B adapter must be able to fall back to a prompt-constrained JSON
request (i.e. instructing the model via the prompt/system message to emit
only JSON matching the `ManagerResponse` shape, without relying on
`response_format`) whenever the configured endpoint's `response_format`
support cannot be confirmed or is rejected by the provider. This fallback
changes only how the *request* is shaped — it must never weaken or bypass
the JSON-parse → Pydantic → `ManagerProposalValidator` pipeline on the
*response* side. A malformed or schema-violating response is rejected by
the existing Stage 8A validator exactly as it would be from any other
source (see Stage 8A's `ManagerInvalidResponseError`/
`ManagerProposalRejectedError`).

### 5.2 Reasoning / Chain-of-Thought (CoT) Handling — corrected field names

* Reasoning is controlled per-request via `chat_template_kwargs`, with the
  documented options being `enable_thinking` (bool), `low_effort` (bool),
  and `medium_effort` (bool) — there is no confirmed simple top-level
  `reasoning_effort` field for this model. A separate thinking-token budget
  cap exists, but its exact parameter name is backend/runtime-dependent
  (observed as `reasoning_budget` nested under `chat_template_kwargs` in
  some vLLM-backed examples, and as `nvext.max_thinking_tokens` in
  NVIDIA Dynamo-backed deployments) — **do not hardcode one universal field
  name**; Stage 8B's adapter must not assume a single name without
  confirming it against the actual deployed backend/runtime it targets.
* When reasoning is enabled and the backend is configured with a
  `--reasoning-parser`, reasoning tokens are separated into a
  `reasoning_content` field (self-hosted NIM, documented). No hosted-surface
  documentation confirming an equivalent separated field was found during
  this pass — treat as NOT VERIFIED on hosted per §4.
* **Keystone production rule (unchanged, restated against corrected names):**
  **NEVER** map `reasoning_content`, `chat_template_kwargs.enable_thinking`/
  `low_effort`/`medium_effort`, `reasoning_budget`, `nvext.max_thinking_tokens`,
  or any `<think>...</think>`-tagged content into `ManagerResponse`. **NEVER**
  persist them. **NEVER** log them. Only the final answer content, safe
  usage metadata (`prompt_tokens`, `completion_tokens`), latency, HTTP
  status, and validated tool calls may cross the adapter boundary into
  Stage 8A.

---

## 6. Tool Calling

Self-hosted NIM auto-tool-choice requires explicit, documented server
configuration:

```
--enable-auto-tool-choice
--tool-call-parser <parser-matching-the-model>   # e.g. qwen3_coder, llama3_json
--reasoning-parser <parser>                       # for models that separate reasoning_content
```

(passable via `NIM_PASSTHROUGH_ARGS` in Kubernetes deployments). No
equivalent hosted-endpoint customer-facing configuration/control was found
during this pass — Stage 8B must not assume the hosted deployment has
been configured with a matching tool-call parser just because self-hosted
NIM documents how to configure one.

NIM's own documentation is also explicit that **NIM does not connect to
MCP servers directly** — a client must convert MCP tool definitions to the
OpenAI `tools` format and execute the tool-call loop itself.

**Stage 8B does not need tool execution for its initial version.**
`ManagerResponse` (Stage 8A, `app.engine.manager.models`) is a structured,
validated *proposal* — task decomposition hints, routing preferences,
verification requirements, a recovery recommendation — never an
autonomous tool-execution loop; Stage 8A's `ManagerOrchestrator` already
never grants a manager proposal tool-execution authority. Tool calling is
therefore an optional, later capability and **must not block Stage 8B
implementation**.

---

## 7. Provider Boundary & Architecture Design

The future `NemotronManagerModel` will implement Stage 8A's `ManagerModel`
Protocol (`app.engine.manager.protocol`, unmodified by this spike) and
communicate through a provider-neutral HTTP boundary.

```
+-------------------------------------------------------+
|              Stage 8A Manager Engine                  |
|                 (ManagerModel Protocol)                |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|             NemotronManagerModel Adapter               |
|   - Formats requests & strips CoT/reasoning fields      |
|   - Sanitizes errors & normalizes usage metadata        |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|        Provider-Neutral HTTP Client Boundary            |
|              (httpx, see 10)                            |
+-------------------------------------------------------+
                           |
            +--------------+--------------+
            |                             |
            v                             v
+-----------------------+     +---------------------------+
| NVIDIA Hosted Endpoint |     | Self-Hosted NIM Container |
| integrate.api.nvidia.com |   | https://<nim-host>:port   |
+-----------------------+     +---------------------------+
```

### Configurable Adapter Schema (Concept — not implemented in this spike)

```python
class NemotronManagerConfig:
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    api_key_env_var: str = "NVIDIA_API_KEY"   # see 8 -- configurable, never NGC_API_KEY by default
    timeout: float = 30.0
    max_tokens: int = 4096
    enable_thinking: bool = False
```

---

## 8. Auth Separation (corrected)

Three distinct credential/concepts exist and must not be conflated:

| Credential | Purpose | Applies to |
| :--- | :--- | :--- |
| Hosted NVIDIA API Catalog credential (conventionally `NVIDIA_API_KEY`, `nvapi-`-prefixed, obtained from `build.nvidia.com`) | Authorizes hosted inference HTTP calls | `integrate.api.nvidia.com` (and other NVIDIA-hosted inference domains) |
| Self-hosted NIM Bearer credential | Optional — self-hosted NIM does not inherently require a Bearer credential for localhost inference unless the deployer explicitly adds authentication | Self-hosted NIM container, only if configured |
| `NGC_API_KEY` | NGC registry / container image pulls (`nvcr.io`) / model download and licensing entitlement | Deployment/ops tooling, container runtime — **not** guaranteed to be an equivalent hosted-inference credential |

Source: [NVIDIA RAG Blueprint — Get an API Key](https://docs.nvidia.com/rag/2.5.0/api-key.html).

**Correction applied:** the original spike's probe script silently fell
back from `NVIDIA_API_KEY` to `NGC_API_KEY` for hosted inference calls,
treating them as interchangeable. That fallback has been removed (see
§0 and the updated `scripts/spikes/nemotron_probe.py`). The recommended
pattern is a configurable `api_key_env_var` (default `NVIDIA_API_KEY`,
appropriate for a hosted Keystone deployment) rather than an automatic
multi-variable fallback chain — an operator who genuinely wants to use a
different variable (including `NGC_API_KEY`, if their deployment happens
to reuse it for inference) sets `api_key_env_var` explicitly.

**Secret values are never printed or logged** by the probe script or by
the recommended adapter design — only credential *availability* (a
boolean) and, on error, a regex-redacted error string.

---

## 9. Self-Hosted Hardware (corrected)

Nemotron 3 Ultra is a datacenter-scale model. Supported GPU count and
precision depend on the current NIM profile and GPU SKU — there is no
single fixed hardware requirement, and none should be frozen into Keystone
design. Consult NVIDIA's current support matrix
([NIM LLM Support Matrix](https://docs.nvidia.com/nim/large-language-models/latest/reference/support-matrix.html))
for the authoritative, versioned table.

Illustrative examples observed in that matrix at the time of this pass
(subject to change in future NIM releases — do not treat as fixed):

* Minimum observed profile: 2 GPUs, `vllm-nvfp4-tp2-pp1`, on high-memory
  Blackwell SKUs (e.g. `B300-SXM6-AC`, `GB300`).
* BF16 profiles require `TP8` (8 GPUs); verified GPU SKUs across profiles
  include B200, B300-SXM6-AC, GB200, GB300, H100-80GB-HBM3, H100-NVL, and
  H200.
* Storage: roughly 330 GB for NVFP4 profiles, 1.1–1.7 TB for BF16 profiles.
* No `TP1` (single-GPU) profile is supported for this model at any
  precision, per the matrix at the time of this pass.

---

## 10. Dependency & Client Recommendation

* **Recommendation:** use the existing `httpx` dependency. It is already
  present in this repository's `pyproject.toml` (currently declared in the
  `dev`/`dependency-groups` sections, used today for FastAPI's
  `TestClient`) and in `uv.lock` — a real Stage 8B implementation would
  need to add it to the main `[project].dependencies` list, but that is a
  one-line dependency-scope change for that implementation PR, not a new
  dependency, and is explicitly **not** made in this documentation-only
  spike (`pyproject.toml`/`uv.lock` are out of scope here — see the DO NOT
  list).
* **Avoid:** adding the `openai` SDK, an Anthropic SDK, or any NVIDIA/NGC
  SDK (`nemo_toolkit`, `ngc-cli`) for this. Stage 8B's actual wire-protocol
  needs are narrow — `POST /v1/chat/completions`, an optional `Authorization:
  Bearer` header, a timeout, a bounded response body read, and sanitized
  status-code handling — all of which `httpx` already covers with no
  additional dependency weight.
* **This spike adds zero dependencies.** `pyproject.toml` and `uv.lock` are
  untouched by this hardening pass.

---

## 11. Failure Matrix & Retry Policy

### 11.1 Failure Mapping Table

| Provider HTTP Error / State | Normalized Keystone Error | Action / Behavior |
| :--- | :--- | :--- |
| **401 Unauthorized** | `AuthenticationError` | Fail immediately; redact key in logs |
| **429 Too Many Requests** | `RateLimitError` | Retry with exponential backoff & respect `Retry-After` |
| **408 / Timeout** | `TimeoutError` | Retry up to max attempts |
| **500 / 502 / 503 / 504** | `ProviderServerError` | Retry bounded |
| **400 Bad Request / Invalid JSON** | `InvalidResponseError` | Fail immediately |
| **Schema Validation Failure** | `ManagerResponseValidationError` | Fail immediately; trigger fallback router |
| **Context Length Exceeded** | `ContextWindowExceededError` | Fail immediately |

### 11.2 Retry Policy

* **Max Retries:** 3 attempts.
* **Backoff Strategy:** Exponential backoff with random jitter (e.g. 1.0s,
  2.0s, 4.0s). Respect `Retry-After` HTTP header if provided by NVIDIA.
* **Non-Retryable:** Do NOT retry 400, 401, 403, 404, or Pydantic
  validation errors.

This design table is Keystone's own internal reliability policy, not an
NVIDIA capability claim, and is unchanged by this hardening pass.

---

## 12. Hosted vs. Self-Hosted (NIM) Deployment Tradeoffs

Distinct from the technical capability matrix in §4 — this table covers
operational/deployment tradeoffs, not per-endpoint capability verification.

| Dimension | Hosted API (`integrate.api.nvidia.com`) | Self-Hosted NIM Microservice |
| :--- | :--- | :--- |
| **Setup Complexity** | Zero (API key registration only) | High (Docker, NVIDIA Container Toolkit, K8s) |
| **Hardware Requirement** | None (cloud hosted) | Profile-dependent — see §9; consult NVIDIA's current support matrix, do not assume a fixed GPU count |
| **Developer Velocity** | Immediate | Requires substantial infra engineering |
| **Cost Profile** | Pay per token / trial credits | High fixed monthly GPU hardware / hosting cost |
| **Data Privacy** | Subject to cloud API terms | Air-gapped enterprise compliance |
| **Recommendation** | **Primary choice for dev, test, & production** | Optional enterprise deployment path |

---

## 13. Production Stage 8B: Recommended Minimal Architecture

Deliberately **small**:

* `NemotronManagerModel` — implements Stage 8A's `ManagerModel` Protocol.
* `NemotronConfig` — `base_url`, `model`, `api_key_env_var`, `timeout`,
  `max_tokens`, `enable_thinking` (see §7's concept schema).
* A provider-neutral HTTP transport Protocol (and a test double for it), if
  useful for isolating `httpx` from the adapter's own logic in tests.
* A response parser: final-content extraction, JSON decode, reasoning-field
  stripping (§5.2).
* Sanitized provider error mapping (§11.1) — never leak a raw provider
  payload or credential in an error message (mirrors Stage 8A's own
  `ManagerInvalidResponseError` discipline).

Explicitly **not** in the initial Stage 8B scope:

* Tool execution loop (§6).
* MCP integration (§6).
* A streaming requirement (chat completions streaming exists per §4, but
  Stage 8A's `ManagerModel.propose()` is a single bounded call — streaming
  is a possible future optimization, not a Stage 8B requirement).
* A NIM deployment manager.
* Model download/weight management.
* Any NVIDIA/NGC SDK.
* Reasoning persistence of any kind (§5.2 — hard rule, not a scoping
  choice).

### Initial production adapter path

```
ManagerRequest                         (Stage 8A, app.engine.manager.models)
  -> safe prompt/messages serialization
  -> POST /v1/chat/completions
  -> final content only (strip reasoning fields, §5.2)
  -> JSON decode
  -> ManagerResponse                   (Stage 8A)
  -> ManagerProposalValidator          (Stage 8A)
```

This spike does not implement any of the above — it documents the target
shape for a future, separately-scoped Stage 8B implementation PR.

---

## 14. Environment Credential & Live Smoke Test Status

* **Credential Availability:** `NO` (neither `NVIDIA_API_KEY` nor any other
  configured `api_key_env_var` was found in this environment during this
  hardening pass).
* **Live Smoke Test Result:** `LIVE TEST NOT RUN -- NO CREDENTIAL`.
* **Probe Verification:** Re-ran the hardened `scripts/spikes/nemotron_probe.py`
  offline; confirmed clean execution, correct `LIVE TEST NOT RUN -- NO
  CREDENTIAL` output, and zero secret leakage (see §15).

---

## 15. Security & Isolation Verification

1. **Zero Hardcoded Secrets:** All credentials are dynamically resolved
   from an environment variable named by `api_key_env_var`
   (default `NVIDIA_API_KEY`) — never a hardcoded fallback to `NGC_API_KEY`.
2. **Error Sanitization:** Probe script includes automatic Bearer
   token / API key regex redaction.
3. **No Project Data Leak:** Probe uses static trivial prompts only.
4. **Core Isolation:** Verified 0 modifications to
   `backend/app/engine/manager/**`, `backend/app/engine/**`,
   `backend/tests/**`, `pyproject.toml`, or `uv.lock`.

---

## 16. Official NVIDIA Primary Sources Consulted (this pass)

* [NIM LLM API Reference](https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html) — full endpoint list (OpenAI- and Anthropic-compatible routes, health, metadata)
* [NIM LLM Support Matrix](https://docs.nvidia.com/nim/large-language-models/latest/reference/support-matrix.html) — GPU/profile/precision requirements
* [Get Started with Nemotron 3 Ultra 550B-A55B](https://docs.nvidia.com/nim/large-language-models/2.0.6/day-0/get-started-nemotron-3-ultra.html) — model-specific GPU profiles, context length, deployment prerequisites
* [Tool Calling and MCP Integration](https://docs.nvidia.com/nim/large-language-models/latest/advanced-use-cases/tool-calling-and-mcp.html) — server flags, MCP client-side note
* [Use Claude Code with NIM](https://docs.nvidia.com/nim/large-language-models/latest/ai-assistant-integrations/claude-code.html) — self-hosted `/v1/messages` usage
* [Hosted NVIDIA LLM API Reference](https://docs.api.nvidia.com/nim/reference/llm-apis) — `integrate.api.nvidia.com` base URL and endpoint overview
* [Nemotron 3 Ultra 550B-A55B API Reference](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-ultra-550b-a55b) — `chat_template_kwargs` reasoning-control examples
* [NVIDIA RAG Blueprint — Get an API Key](https://docs.nvidia.com/rag/2.5.0/api-key.html) — `NVIDIA_API_KEY` vs `NGC_API_KEY` distinction
* [NVIDIA API Catalog model card](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/modelcard)

No blog, OpenRouter listing, or third-party model host was used as
capability authority for any VERIFIED row in §4; where such sources came up
during research they were treated as supplementary color at most and
excluded from any capability determination.

---

## 17. Remaining Unverified Hosted Capabilities

The following are **NOT VERIFIED** on the hosted API catalog specifically,
per §4, and must not be assumed by a Stage 8B implementation without
further direct confirmation (e.g. a live authenticated probe once a
credential is available, or a future NVIDIA hosted-API-specific reference
page):

* `/v1/completions` on the hosted surface.
* Reasoning controls (`chat_template_kwargs`) on the hosted surface.
* `response_format` JSON mode on either surface (capability-gated, §5.1).
* Tool calling (`tools`/`tool_choice`) on the hosted surface.
* `/v1/messages` and `/v1/messages/count_tokens` (Anthropic-compatible) on
  the hosted surface.
* `/v1/responses` on the hosted surface.

---

## 18. Final Checklist & Recommendation

- [x] Branch: `feature/stage8b0-nemotron-spike`
- [x] Base commit verified: `b08da8407909f1ba41bd9cf4536b0ead4c4a54f6`
- [x] Anthropic compatibility corrected against current NVIDIA primary docs
- [x] Hosted vs. self-hosted capability matrix added, sourced, marked
      VERIFIED / NOT VERIFIED / NOT APPLICABLE
- [x] Structured output re-scoped to JSON mode, not schema-guaranteed;
      capability-gated where hosted support is unconfirmed
- [x] Tool calling's self-hosted server-configuration requirement
      documented; confirmed non-blocking for Stage 8B
- [x] Reasoning field names corrected to documented values; never-persist/
      never-log rule restated against them
- [x] Auth separated: hosted credential vs. self-hosted (optional) vs.
      `NGC_API_KEY`; configurable `api_key_env_var` recommended
- [x] Hardware requirement de-frozen to profile/SKU-dependent, sourced from
      the current support matrix
- [x] Dependency recommendation: existing `httpx`, zero new dependencies
      added in this spike
- [x] Stage 8B minimal architecture defined, explicitly bounded
- [x] Probe script hardened and re-run offline; Ruff-clean
- [x] Zero `backend/app/engine/manager/**`, `backend/app/engine/**`,
      `backend/tests/**`, `pyproject.toml`, or `uv.lock` modifications

### Recommendation

**READY FOR STAGE 8B IMPLEMENTATION**
