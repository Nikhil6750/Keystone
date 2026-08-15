# Trading Companion — Keystone Orchestration Readiness

Audit date: 2026-08-16
Audited baseline: `main` @ `62958a0f20c6b50c9ff3ede3367f84638101c79e`
Audit method: direct code inspection (file:line citations below), not documentation or aspiration.

## Verdict: **PARTIAL**

Keystone has a real, provider-neutral, evidence-based orchestration engine underneath it — routing, verification, and bounded recovery are genuinely production-grade and reusable as-is. Two things stood between that engine and a safe autonomous build of a project this size: no isolation mechanism for concurrent writers to the same repository, and a task decomposer too narrow (rule-based, 10-task cap) for a goal with 15+ distinct subsystems. This stage closes the first gap for real (implemented, tested, merged in this branch). The second gap — general task decomposition — is not closed here; it requires either a much larger planner rework or a different input contract, and is documented below as the next blocking step before an autonomous Trading Companion build can start.

---

## 1. What Keystone already has (reusable as-is)

**Real, provider-neutral agent execution.** `LocalCLIAdapter._run_process` → `SubprocessRunner.run` (`backend/app/adapters/local_cli.py`, `backend/app/adapters/process_runner.py:122-206`) spawns genuine child processes (`shell=False`, real stdin/stdout, real timeouts) — not stubs. `AntigravityAdapter` (`backend/app/adapters/antigravity.py:20-21`) inherits this verbatim; nothing about any of the three adapters is simulated once enabled.

**Capability/registry-driven routing, not hardcoded.** `Router.route()` / `scorer.py:271-361` picks agents purely on declared capability + historical reliability (`AgentPassportMetricBucket`, Laplace-smoothed, `scorer.py:44-52`) + availability + circuit-breaker state. No engine file hardcodes `claude_code`/`codex`/`antigravity` by name — they're just registry entries with declared `AgentCapability` sets (`runtime.py:53-151`).

**Real verification gates.** `QualityFactoryCoordinator.verify_software_execution()` (`coordinator.py:53-194`) runs actual `pytest -q` / `npm run build` / etc. via `SafeQualityProcessRunner` against the real workspace (`test_executor.py:61-133`, `build_executor.py:67-82`) — genuine exit codes and stdout, not canned pass/fail.

**Bounded, evidence-required retry and reroute.** `RecoveryPolicy.max_attempts` (default 3) bounds both `QualityRepairManager` (`repair.py:33-36`) and `decide_recovery`/`reroute` (`recovery.py:64,141-148,189-210` — reroute explicitly excludes the agent that just failed). A second, independent bound covers transient execution retries (`RetryingStepRunner`, `retry_runner.py:63-103`) with exponential backoff and a circuit breaker (`circuit_breaker.py`). Neither loop can spin forever, and each attempt requires a fresh verification outcome, never a blind rerun.

**One goal → multi-task dependency-aware execution, already end-to-end.** `EndToEndOrchestrationService.orchestrate()` (`service.py`) runs Planning → Skill enrichment → Routing → compiled `WorkflowEngine` execution (parallel where `parallel_safe`, bounded by `max_concurrency=3`) → Verification → Recovery → Learning, in one call, against a real `workspace_root`.

## 2. Claude Code runtime status: **REAL, config-gated, disabled by default**
Genuine subprocess execution via `LocalCLIAdapter`/`SubprocessRunner`. Gated by `KEYSTONE_CLAUDE_CODE_ENABLED` (`config.py:81-83`, default `false`) and PATH resolution at `factory.register_agents()` (`factory.py:66-109`) — only wired into the live `ExecutorRegistry` (and therefore only ever selectable by `RegistryCandidateProvider`, `runtime.py:188-273`) if both enabled and resolvable. Full capability set declared (`runtime.py:56-80`: code generation, test execution, planning, etc.).

## 3. Codex runtime status: **REAL, config-gated, disabled by default**
Same mechanism as Claude Code, same file, same gating (`config.py:123`, `runtime.py:81-97`). Full capability set declared, matching Claude Code's breadth.

## 4. Antigravity runtime status: **REAL task execution confirmed — not detection-only**
This was the one requiring the most scrutiny, since Antigravity is also independently *detectable* as an installed IDE/runtime. Both paths exist and are distinct: `detect()` (`local_cli.py:94-100`) is a `shutil.which` presence check; `check_authentication()` returns `UNKNOWN` for Antigravity by design (no safe non-interactive auth-status probe exists); but `execute()` — the real task path — is inherited unmodified from `LocalCLIAdapter` and genuinely spawns `agy --print <prompt> ...` through the same `SubprocessRunner` used by Claude Code and Codex. Gated by `KEYSTONE_ANTIGRAVITY_ENABLED` (`config.py:164-166`, default `false`). **Conclusion: Antigravity is programmatically invocable by Keystone for real task execution, not merely detectable.** A standalone live-proof script exists (`backend/scripts/certify_live_multiagent.py`) that force-enables all three and requires ≥2 real installed/authenticated runtimes or exits `BLOCKED`; it is not wired into CI, so a passing run's evidence is not currently reproduced automatically — running it once against this machine's real installs is a recommended pre-flight check before the Companion build starts, not a blocker in itself.

Gemini (the standalone CLI, distinct from Antigravity) exists in the registry with a narrower declared capability set (`CODE_GENERATION`, `GENERAL_REASONING` only, `runtime.py:98-103`) and is not part of the requested team; noted for completeness.

## 5. Exact missing capabilities

| Capability | Status before this stage | Status after this stage |
|---|---|---|
| Concurrent-write isolation on a shared target repo | **Missing.** Zero "worktree" references anywhere in `backend/app`; every step shared one `cwd` (`workflow_engine.py:958`), with only advisory `parallel_safe`/`target_files_ownership` planning metadata — no runtime lock. | **Implemented, opt-in.** See §6. |
| General task decomposition for a novel, large, multi-domain goal | **Missing.** `Planner`→`TaskGraphCompilerV2` is a fixed ~10-case if/elif cascade with literal filenames (`compiler.py:311-1097`), no LLM call anywhere (`planner.py:5`), hard-capped at `MAX_TASKS=10`/`MAX_DEPTH=5` (`compiler.py:102-103`). A goal like the Trading Companion's would fall into the generic fullstack fallback and produce a shallow 3-5 node graph blind to PWA/websocket/voice/character-state as distinct concerns. | **Not addressed in this stage** (see §9 — this is the real remaining blocker). |
| Cross-agent adversarial review ("Claude proposes, Codex critiques") | **Missing.** `consensus.py` only compares *already-produced, independently-verified* outputs for byte-equality (`consensus.py:100-205`) — never reasoning-level critique before acceptance. No hits anywhere for "independent review"/"counter-proposal"/"critique". | **Not addressed in this stage.** |
| Project-level (not just per-task) acceptance gate | **Missing.** No "whole project is done" concept anywhere; everything is keyed by `task_id`/`execution_id`. | **Not addressed in this stage.** |

## 6. Workspace/repository isolation strategy — implemented this stage

Added `app.engine.orchestration.workspace_isolation.GitWorktreeIsolationManager`, wired into `EndToEndOrchestrationService.orchestrate()` behind a new, **opt-in, default-`False`** field: `OrchestrationRequest.isolate_workspace`.

- **Default (`isolate_workspace=False`)**: byte-for-byte identical behavior to before this stage — verified by a dedicated regression test.
- **When `True`**: this orchestration run gets its own `git worktree` (`git worktree add -b keystone/run-<sanitized request_id> ...`) off the target repo's current branch. Every step in this run's `WorkflowPlan` executes inside that worktree, not the shared checkout — a second, concurrent `orchestrate()` call against the same repo (e.g. a different Trading Companion subsystem being built in parallel) gets its own independent worktree and never touches this one's working tree or index.
- On successful completion, any pending changes the agent left uncommitted are committed, then `git merge --no-ff` integrates the branch back into the base branch in the *original* checkout, and the worktree/branch are cleaned up.
- On a merge conflict (`WorkspaceIntegrationConflictError`) or any setup failure (`WorkspaceIsolationSetupError`), the merge is aborted (leaving the base checkout clean) and the run's branch/worktree are preserved, never deleted — the work is never silently lost, but automatic conflict resolution is explicitly out of scope for this stage; a conflict currently requires human (or a future repair-cycle) resolution.
- **Scope, deliberately bounded**: this isolates one orchestration *run* from another *run* sharing a repo. It does not add isolation *within* one already-coordinated `WorkflowPlan`'s own concurrently-scheduled steps — those still rely on the planner's `parallel_safe`/`target_files_ownership` metadata plus `WorkflowEngine`'s bounded concurrency, unchanged. Extending isolation to per-step granularity inside one workflow would require changes to `WorkflowEngine`/`GraphScheduler` themselves — a larger change, deliberately not attempted here per "do not redesign working subsystems."

**Recommended usage for the Companion build**: run each top-level subsystem (backend, laptop UI, PWA, voice pipeline, etc.) as a separate `orchestrate()` call with `isolate_workspace=True` against the same Companion repo, so subsystems being built concurrently by different agents never corrupt each other's working tree — while tasks *within* one subsystem's own workflow continue to rely on the existing `parallel_safe` ownership metadata.

## 7. Task DAG strategy (current state, unchanged this stage)
`TaskGraphCompilerV2` (`compiler.py:95-1183`) does produce a genuine dependency-aware DAG — cycle-checked, depth-bounded, `parallel_safe` derived from real file-ownership overlap (`compiler.py:1099-1175`) — but only for the fixed goal shapes its case list recognizes. **This is the actual blocker for the Companion.** Recommended path (not implemented here, scope explicitly excluded by "do not redesign working subsystems" and by the instruction to implement only the smallest necessary change): either (a) accept a structured task list as a direct `WorkflowPlan`/`TaskSpec[]` input alongside the existing free-text `goal`, bypassing `TaskClassifier`/the case cascade entirely for large novel projects — the compiler's DAG *validation* (cycle/depth/ownership derivation) can still run over externally-supplied nodes without any planner rework — or (b) raise `MAX_TASKS`/`MAX_DEPTH` and add new dedicated cases for this project's shape. (a) is the smaller, safer change and is the recommended next stage.

## 8. Verification strategy (current state, unchanged this stage)
Real, per-task, already reusable as-is (§1). For the Companion specifically: `TestQualityGateExecutor`/`BuildQualityGateExecutor` already run real `npm test`/`npm run build`/`pytest` — sufficient for backend, PWA build, and unit-test gates. Browser/E2E verification (explicitly requested for Antigravity/Gemini's role) has no existing executor — `executors/` covers `build`/`lint`/`test`/`type_check`/`custom`/`mock` (`backend/app/engine/quality/executors/__init__.py`) but nothing browser-automation-specific. A `custom` gate (already a supported `QualityGateExecutor` type) can wrap a Playwright/Cypress invocation without any new engine code — recommended, not a Keystone change.

## 9. Retry/reroute strategy (current state, unchanged this stage)
Reusable as-is (§1) — bounded, evidence-based, reroute avoids repeating the same failed agent. No changes needed for the Companion build.

## 10. Minimal changes required in Keystone

Implemented in this branch (`feature/keystone-orchestration-readiness`):
- `backend/app/engine/orchestration/workspace_isolation.py` (new)
- `OrchestrationRequest.isolate_workspace` field (additive, default `False`)
- `WorkspaceIsolationSetupError` / `WorkspaceIntegrationConflictError` (new, in `errors.py`)
- `EndToEndOrchestrationService.orchestrate()` split into a thin wrapper + unmodified `_orchestrate_inner()` (mechanical rename, zero logic change to the inner method)

**Not implemented, required before an autonomous end-to-end Companion build can safely start:**
1. A way to feed the compiler a large, novel, externally-structured task graph (§7) — without this, `orchestrate()` will either reject the Companion goal's scale (`MAX_TASKS=10`) or silently under-decompose it into a generic fullstack graph that misses most of the requested scope.
2. A cross-agent review step for architecture-critical decisions (per the task's explicit "Claude proposes → Codex critiques → Keystone evaluates" requirement) — currently no mechanism exists; the smallest version of this is a new task type whose executor is "run agent A, feed its output as context to agent B with a critique prompt, surface both to a human/gate before the design proceeds," which can be built as an ordinary quality gate (`custom` executor) plus a routing convention, without touching the engine's core abstractions.
3. A project-level acceptance concept, if "the whole Companion is done" needs to be machine-checkable rather than a human looking at N `orchestrate()` results.

## 11. Is Keystone ready to launch the Companion build now?

**Not yet, for the full scope as specified.** The routing/execution/verification/recovery core is genuinely ready and reusable today, and concurrent-repo-write safety (the item explicitly flagged as a launch blocker) is now real. The blocking gap is task decomposition generality (§7/§10.1): without it, a single `orchestrate()` call cannot faithfully decompose "build a trading companion with a laptop UI, iPhone PWA, shared backend, websocket layer, character/state system, voice input/output, wake-word activation, mock setup events, canonical JSON schema, and Claude-powered explanations" into the ~15-20+ distinct, correctly-dependency-ordered tasks that scope actually requires.

**Recommended immediate next step**, not taken in this stage per the instruction to implement only the smallest necessary capability: decide between §7's option (a) or (b), implement it as its own reviewed change, then run one real `orchestrate(isolate_workspace=True)` call against a throwaway Companion scaffold repo as a live readiness proof before committing to the full build.
