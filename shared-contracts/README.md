# `shared-contracts`

`shared-contracts` is the central, technology-agnostic TypeScript contract package for the Keystone AI Agent Orchestration Platform. It defines pure interfaces, status types, and event schemas shared across all subsystems.

---

## 🎯 Purpose of `shared-contracts`

In a multi-developer, multi-tier system, having a single source of truth for domain contracts prevents schema drift, integration bugs, and communication breakdowns. 

`shared-contracts` defines:
- **Agents Domain**: Agent models, status types, and capabilities.
- **Workflow Domain**: Workflow structures, step definitions, lifecycle statuses, and execution events.
- **Knowledge Domain**: Document representations and search result contracts.
- **Extension & IPC Domain**: Standardized request and response envelopes for IDE extensions and CLI adapters.

---

## 👥 Consumers

| Subsystem | Owner | Consumption Role |
| :--- | :--- | :--- |
| **Backend Orchestrator** | **Developer 1** | Aligns REST API DTOs and WebSocket payload structures with these contracts. |
| **VS Code Extension** | **Developer 2** | Consumes types for Webview state management, IPC messaging, and status views. |
| **CLI & Connectors** | **Developer 3** | Uses contracts for CLI request formatting, agent connector status reporting, and event output. |

---

## 📜 Rules for Modifying Contracts

To maintain system integrity and prevent breaking changes:

1. **Non-Breaking Additions Only**: New optional fields (`field?: Type`) or new interfaces may be added without major version bumps.
2. **No Field Deletions or Renames**: Fields must not be deleted or renamed directly. Use deprecation notices and schedule breaking changes across developers.
3. **No Implementation Code**: This package MUST NOT contain runtime business logic, API callers, mock data, backend code, or UI framework code (e.g. React).
4. **All Changes Require Review**: Any PR modifying `shared-contracts` requires explicit review and approval from all domain owners (Developer 1, Developer 2, and Developer 3).

---

## 🔒 Why Contracts Must Remain Stable

1. **Independent Development**: Allows Developer 1, Developer 2, and Developer 3 to work in parallel without blocking each other.
2. **Zero Incompatible Merges**: Prevents merge conflicts between backend JSON representations and client TypeScript models.
3. **Robust IPC & API Layer**: Standardized `ExtensionRequest` and `EngineResponse` envelopes ensure predictable inter-process communication between VS Code, CLI, and Backend services.
