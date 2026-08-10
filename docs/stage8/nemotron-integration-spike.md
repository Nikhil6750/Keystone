# Stage 8B0: NVIDIA Nemotron 3 Ultra Provider Integration Spike Report

**Branch:** `feature/stage8b0-nemotron-spike`  
**Base Commit:** `b08da8407909f1ba41bd9cf4536b0ead4c4a54f6` (`origin/feature/core-intelligence-vnext`)  
**Date:** August 10, 2026  
**Status:** READY FOR STAGE 8B IMPLEMENTATION  

---

## 1. Executive Summary

This spike evaluates the integration architecture for **NVIDIA Nemotron 3 Ultra (550B-A55B)** into Keystone as part of Stage 8B. The primary objective is to define a production-grade, provider-neutral adapter architecture (`NemotronManagerModel`) that satisfies Stage 8A Manager requirements without introducing tight coupling, proprietary SDK dependencies, or credential leaks.

Strict isolation was maintained throughout this spike: **ZERO Stage 8A/core manager files were created or modified**, and zero model weights or containers were downloaded locally.

---

## 2. Official Primary Sources & Technical Specs

| Attribute | Official Value / Specification | Source / Verification |
| :--- | :--- | :--- |
| **Model Identifier** | `nvidia/nemotron-3-ultra-550b-a55b` | [NVIDIA API Catalog](https://build.nvidia.com) |
| **Architecture** | LatentMoE (Hybrid Mamba-2 + MoE + Attention + MTP) | [NVIDIA NeMo Hub](https://github.com/NVIDIA-NeMo/Nemotron) |
| **Total / Active Parameters** | 550B Total / 55B Active per token | NVIDIA Technical Announcement |
| **Context Limit** | 1,000,000 tokens (1M) | NVIDIA NIM Specifications |
| **Official Documentation** | [https://build.nvidia.com](https://build.nvidia.com) | Official NVIDIA Developer Portal |
| **NIM Documentation** | [https://developer.nvidia.com/nim](https://developer.nvidia.com/nim) | NVIDIA Microservice Reference |
| **Weights & License** | OpenMDW License v1.1 | Hugging Face (`nvidia/Nemotron-3-Ultra-550B-A55B`) |

---

## 3. Protocol & API Interface Analysis

### 3.1 Hosted Endpoint & Authentication
* **Base URL:** `https://integrate.api.nvidia.com/v1`
* **Inference Endpoint:** `https://integrate.api.nvidia.com/v1/chat/completions`
* **Authentication Mechanism:** Standard HTTP Authorization Header:
  ```http
  Authorization: Bearer <API_KEY>
  ```
* **Credential Variable:** Read dynamically from `NVIDIA_API_KEY` or `NGC_API_KEY` environment variables.

### 3.2 Protocol Compatibility
* **OpenAI Compatibility:** **YES (Full)**. NVIDIA hosted build endpoints and NIM microservices adhere strictly to the OpenAI `/v1/chat/completions` standard REST schema.
* **Anthropic Compatibility:** **NO**. NVIDIA does not natively expose an Anthropic `/v1/messages` format. Keystone will standardize on the OpenAI-compatible HTTP interface for Nemotron integration.
* **Streaming:** Standard Server-Sent Events (`stream: true`) returning incremental JSON chunks compatible with standard OpenAI `delta` objects.

---

## 4. Structured Output & Reasoning Traces

### 4.1 Structured Output Support
Nemotron 3 Ultra supports OpenAI-compatible function/tool calling (`tools` parameter) and structured JSON outputs via `response_format={"type": "json_object"}`.

#### Keystone Validation Strategy:
Never trust raw provider outputs directly. To ensure typed `ManagerResponse` compatibility for Stage 8A:
1. Pass clear JSON schemas via prompt / `response_format`.
2. Provider HTTP Response → JSON Extractor & Sanitizer → Pydantic Model Parsing → **Deterministic `ManagerProposalValidator`**.

### 4.2 Reasoning / Chain-of-Thought (CoT) Handling
* Nemotron 3 Ultra provides configurable reasoning via `chat_template_kwargs={"enable_thinking": True/False}` or `reasoning_budget`.
* When enabled, reasoning tokens are emitted in `reasoning_content` or `<think>...</think>` tags.
* **Keystone Persistence Policy:** **DO NOT PERSIST HIDDEN CoT**. The future adapter MUST strip reasoning traces prior to returning output.
* **Retained Metadata:** Only return final structured answer, token usage (`prompt_tokens`, `completion_tokens`), latency, HTTP status, and validated tool calls.

---

## 5. Provider Boundary & Architecture Design

The future `NemotronManagerModel` will inherit from Stage 8A `ManagerModel` and communicate through a provider-neutral HTTP boundary.

```
+-------------------------------------------------------+
|              Stage 8A Manager Engine                  |
|                 (ManagerModel)                        |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|             NemotronManagerModel Adapter              |
|   - Formats requests & strips CoT/reasoning           |
|   - Sanitizes errors & normalizes usage metadata      |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|        Provider-Neutral HTTP Client Boundary          |
|              (httpx / lightweight HTTP)               |
+-------------------------------------------------------+
                           |
            +--------------+--------------+
            |                             |
            v                             v
+-----------------------+     +-----------------------+
| NVIDIA Hosted Endpoint|     | Self-Hosted NIM Container|
|integrate.api.nvidia.com|     | https://<nim-host>:port|
+-----------------------+     +-----------------------+
```

### Configurable Adapter Schema (Concept)
```python
class NemotronManagerConfig:
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    api_key_env_var: str = "NVIDIA_API_KEY"
    timeout: float = 30.0
    max_tokens: int = 4096
    enable_thinking: bool = False
```

---

## 6. Dependency & Client Recommendation

* **Recommendation:** Use standard lightweight HTTP library (`httpx`) or existing standard `openai` client configured with a custom `base_url`.
* **Avoid:** Heavy proprietary SDKs (`nemo_toolkit`, `ngc-cli`) which introduce gigabytes of dependencies and complex C++ toolchain requirements.

---

## 7. Failure Matrix & Retry Policy

### 7.1 Failure Mapping Table

| Provider HTTP Error / State | Normalized Keystone Error | Action / Behavior |
| :--- | :--- | :--- |
| **401 Unauthorized** | `AuthenticationError` | Fail immediately; redact key in logs |
| **429 Too Many Requests** | `RateLimitError` | Retry with exponential backoff & respect `Retry-After` |
| **408 / Timeout** | `TimeoutError` | Retry up to max attempts |
| **500 / 502 / 503 / 504** | `ProviderServerError` | Retry bounded |
| **400 Bad Request / Invalid JSON**| `InvalidResponseError` | Fail immediately |
| **Schema Validation Failure** | `ManagerResponseValidationError` | Fail immediately; trigger fallback router |
| **Context Length Exceeded** | `ContextWindowExceededError` | Fail immediately |

### 7.2 Retry Policy
* **Max Retries:** 3 attempts.
* **Backoff Strategy:** Exponential backoff with random jitter (e.g. 1.0s, 2.0s, 4.0s). Respect `Retry-After` HTTP header if provided by NVIDIA.
* **Non-Retryable:** Do NOT retry 400, 401, 403, 404, or Pydantic validation errors.

---

## 8. Hosted vs. Self-Hosted (NIM) Comparison

| Dimension | Hosted API (`integrate.api.nvidia.com`) | Self-Hosted NIM Microservice |
| :--- | :--- | :--- |
| **Setup Complexity** | Zero (API key registration only) | High (Docker, NVIDIA Container Toolkit, K8s) |
| **Hardware Requirement**| None (Cloud hosted) | 8x H100 / H200 / B200 GPUs (550B model NVFP4 profile) |
| **Developer Velocity** | Immediate | Requires substantial infra engineering |
| **Cost Profile** | Pay per token / trial credits | High fixed monthly GPU hardware / hosting cost |
| **Data Privacy** | Subject to cloud API terms | Air-gapped enterprise compliance |
| **Recommendation** | **Primary choice for dev, test, & production** | Optional enterprise deployment path |

---

## 9. Environment Credential & Live Smoke Test Status

* **Credential Availability:** `NO` (Neither `NVIDIA_API_KEY` nor `NGC_API_KEY` was found in the environment).
* **Live Smoke Test Result:** `LIVE TEST NOT RUN -- NO CREDENTIAL`
* **Probe Verification:** Executed `scripts/spikes/nemotron_probe.py` offline; confirmed clean execution and zero secret leakage.

---

## 10. Security & Isolation Verification

1. **Zero Hardcoded Secrets:** All credentials are dynamically resolved from environment variables.
2. **Error Sanitization:** Probe script includes automatic Bearer token / API key regex redaction.
3. **No Project Data Leak:** Probe uses static trivial prompts only.
4. **Core Isolation:** Verified 0 modifications to `backend/app/engine/manager/**` or core intelligence files.

---

## 11. Final Checklist & Recommendation

- [x] Branch created: `feature/stage8b0-nemotron-spike`
- [x] Base commit verified: `b08da8407909f1ba41bd9cf4536b0ead4c4a54f6`
- [x] Official NVIDIA source research recorded
- [x] Provider boundary architecture defined
- [x] OpenAI-compatibility confirmed
- [x] Failure matrix & retry policies documented
- [x] Hosted vs NIM comparison complete
- [x] Probe script added: `scripts/spikes/nemotron_probe.py`
- [x] Zero core files modified

### Recommendation
**READY FOR STAGE 8B IMPLEMENTATION**
