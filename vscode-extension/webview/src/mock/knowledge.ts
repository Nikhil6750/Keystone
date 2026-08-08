export interface KnowledgeDocument {
  id: string;
  title: string;
  source: string;
  tags: string[];
  lastUpdated: string;
  preview: string;
  metadata: {
    author: string;
    version?: string;
    status?: string;
    category: string;
    wordCount: number;
    checksum?: string;
  };
}

export const MOCK_KNOWLEDGE_DOCUMENTS: KnowledgeDocument[] = [
  {
    id: 'doc-workflow-engine',
    title: 'Workflow Engine Architecture',
    source: 'docs/architecture.md',
    tags: ['orchestration', 'state-machine', 'saga', 'backend'],
    lastUpdated: '2026-08-08 10:15:00',
    preview:
      'The Keystone Workflow Engine executes multi-step saga workflows across heterogeneous AI coding agents. It enforces strict finite state machine transitions (PENDING → RUNNING → COMPLETED/FAILED → COMPENSATING → COMPENSATED) and records every transition in a tamper-evident audit log.',
    metadata: {
      author: 'Developer 1',
      version: 'v0.2.0',
      status: 'Stable',
      category: 'Core Architecture',
      wordCount: 1420,
      checksum: 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    },
  },
  {
    id: 'doc-shared-contracts',
    title: 'Shared Contracts Specification',
    source: 'shared-contracts/README.md',
    tags: ['types', 'typescript', 'contracts', 'architecture'],
    lastUpdated: '2026-08-08 09:30:00',
    preview:
      'Central technology-agnostic TypeScript contract package defining common models for Agents, Workflows, Knowledge, and Extension IPC messaging. Reused across Backend, Extension Host, and Webview UI.',
    metadata: {
      author: 'Keystone Architect',
      version: 'v0.1.0',
      status: 'Active Contract',
      category: 'Shared Specifications',
      wordCount: 890,
      checksum: 'sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
    },
  },
  {
    id: 'doc-sprint-planning',
    title: 'Sprint Planning & Roadmap',
    source: 'docs/backend-build-plan.md',
    tags: ['planning', 'roadmap', 'sprints', 'process'],
    lastUpdated: '2026-08-07 16:45:00',
    preview:
      'Multi-sprint architecture roadmap outlining Sprint 0 (Shared Contracts), Sprint 1 (Extension Shell), Sprint 2 (Workflow Builder), Sprint 3 (Agent Manager), and Sprint 4 (Knowledge Explorer).',
    metadata: {
      author: 'Project Lead',
      version: 'v1.0.0',
      status: 'In Progress',
      category: 'Project Management',
      wordCount: 2100,
    },
  },
  {
    id: 'doc-backend-architecture',
    title: 'Backend Architecture Overview',
    source: 'backend/app/main.py',
    tags: ['python', 'fastapi', 'sqlalchemy', 'backend'],
    lastUpdated: '2026-08-06 14:00:00',
    preview:
      'FastAPI-powered Python 3.12 backend service. Contains modular routing controllers, SQLAlchemy ORM persistence with SQLite (`keystone.db`), Pydantic request/response schemas, and dependency injection providers.',
    metadata: {
      author: 'Developer 1',
      version: 'v0.1.0',
      status: 'Stable',
      category: 'Backend Core',
      wordCount: 1750,
      checksum: 'sha256:4b227777d4da1691de7168d05269588f36c84f01b0242208f4b16857fca74347',
    },
  },
  {
    id: 'doc-retry-strategy',
    title: 'Resilience & Retry Strategy',
    source: 'backend/app/resilience/retry.py',
    tags: ['resilience', 'circuit-breaker', 'retry', 'fault-tolerance'],
    lastUpdated: '2026-08-05 11:20:00',
    preview:
      'Implements per-agent circuit breakers (CLOSED → OPEN → HALF-OPEN) and exponential backoff retry policies to isolate failing agent CLIs without interrupting the broader workflow execution.',
    metadata: {
      author: 'Developer 1',
      version: 'v0.2.0',
      status: 'Stable',
      category: 'Fault Tolerance',
      wordCount: 1150,
    },
  },
  {
    id: 'doc-scheduler',
    title: 'Step Scheduler & Executor',
    source: 'backend/app/engine/executor.py',
    tags: ['executor', 'scheduler', 'process-runner', 'sync'],
    lastUpdated: '2026-08-04 18:30:00',
    preview:
      'Orchestrates sequential step execution by dispatching tasks to registered agent subprocess runners. Captures stdout, stderr, and process exit codes into structured attempt logs.',
    metadata: {
      author: 'Developer 1',
      version: 'v0.1.5',
      status: 'Active',
      category: 'Orchestration Engine',
      wordCount: 980,
    },
  },
  {
    id: 'doc-agent-registry',
    title: 'Agent Registry & Capability Matrix',
    source: 'backend/app/services/agent_availability.py',
    tags: ['agents', 'registry', 'capabilities', 'connectors'],
    lastUpdated: '2026-08-04 15:10:00',
    preview:
      'Registry mapping canonical agent types (`claude_code`, `codex`, `antigravity`, `openrouter`, `demo`) to installation verification routines, version detectors, and execution capability sets.',
    metadata: {
      author: 'Developer 3',
      version: 'v0.2.0',
      status: 'Stable',
      category: 'Agent Management',
      wordCount: 1320,
    },
  },
  {
    id: 'doc-openrouter-adapter',
    title: 'OpenRouter Gateway Adapter',
    source: 'docs/live-agent-connectors.md',
    tags: ['openrouter', 'llm-routing', 'gateway', 'fallback'],
    lastUpdated: '2026-08-03 17:00:00',
    preview:
      'Specification for the OpenRouter multi-model API adapter. Enables fallback routing across cloud LLM providers when local CLI tools are unavailable or unauthenticated.',
    metadata: {
      author: 'Developer 3',
      version: 'v0.1.0',
      status: 'Draft Spec',
      category: 'Connectors',
      wordCount: 840,
    },
  },
  {
    id: 'doc-claude-connector',
    title: 'Claude Code CLI Connector',
    source: 'backend/app/adapters/claude_code.py',
    tags: ['claude-code', 'anthropic', 'cli', 'subprocess'],
    lastUpdated: '2026-08-03 14:15:00',
    preview:
      'Headless subprocess runner for Anthropic Claude Code CLI (`claude`). Uses existing local OS user authentication tokens without passing credentials through HTTP payload parameters.',
    metadata: {
      author: 'Developer 3',
      version: 'v0.2.29',
      status: 'Verified',
      category: 'Connectors',
      wordCount: 1050,
      checksum: 'sha256:7c9e667973714264aee17800163acadf2b60408b082414c0897f26d217036683',
    },
  },
  {
    id: 'doc-vscode-extension',
    title: 'VS Code Extension Architecture',
    source: 'vscode-extension/README.md',
    tags: ['vscode', 'extension', 'webview', 'react', 'vite'],
    lastUpdated: '2026-08-08 12:00:00',
    preview:
      'Architecture guide for the Keystone VS Code Extension. Describes the Extension Host lifecycle, Activity Bar integration, Sidebar view, Status Bar item, and postMessage bridge to the React+Vite Webview.',
    metadata: {
      author: 'Developer 2',
      version: 'v0.1.0',
      status: 'Active',
      category: 'IDE Integration',
      wordCount: 1680,
    },
  },
  {
    id: 'doc-obsidian-vault',
    title: 'Obsidian Knowledge Vault Spec',
    source: 'docs/knowledge-vault-spec.md',
    tags: ['obsidian', 'markdown', 'vault', 'knowledge-base'],
    lastUpdated: '2026-08-02 09:00:00',
    preview:
      'Future specification for indexing local Markdown Obsidian vaults. Outlines frontmatter parsing, wikilink extraction (`[[Link]]`), and automated knowledge graph indexing for Phase 7.',
    metadata: {
      author: 'Architect',
      version: 'v0.0.1',
      status: 'Future Plan',
      category: 'Knowledge Systems',
      wordCount: 650,
    },
  },
  {
    id: 'doc-engine-api',
    title: 'Keystone Engine REST API Specs',
    source: 'docs/api-contract.md',
    tags: ['api', 'rest', 'endpoints', 'openapi', 'schemas'],
    lastUpdated: '2026-08-04 10:00:00',
    preview:
      'Complete REST API contract reference listing endpoints for `/workflows`, `/agents`, `/audit`, `/resilience`, and `/health`, including error code envelopes and payload schemas.',
    metadata: {
      author: 'Developer 1',
      version: 'v0.2.0',
      status: 'Stable Contract',
      category: 'API Specifications',
      wordCount: 2450,
    },
  },
];
