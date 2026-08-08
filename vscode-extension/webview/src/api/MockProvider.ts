export interface AgentItem {
  id: string;
  name: string;
  type: string;
  installationStatus: 'Installed' | 'Not Installed';
  version: string;
  executable: string;
  authenticationStatus: 'Authenticated' | 'Needs Authentication' | 'Unauthenticated';
  connectionStatus: 'Connected' | 'Disconnected' | 'Unknown';
  lastVerifiedAt: string;
  capabilities: string[];
  description: string;
  iconName: string;
}

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

export type ExecutionStatus = 'Waiting' | 'Running' | 'Completed';

export interface StageDefinition {
  id: string;
  title: string;
  description: string;
  iconName: string;
  durationMs: number;
  logs: string[];
}

export interface LogEntry {
  id: string;
  stageId: string;
  stageTitle: string;
  message: string;
  timestamp: string;
}

export interface Suggestion {
  id: string;
  title: string;
  description: string;
  promptText: string;
  iconName: string;
}

export interface WorkspaceNodeItem {
  id: string;
  name: string;
  relativePath: string;
  kind: 'file' | 'directory';
  size?: number;
  extension?: string;
  lastModified?: string;
  preview?: string;
  children?: WorkspaceNodeItem[];
}

const INITIAL_AGENTS: AgentItem[] = [
  {
    id: 'claude-code',
    name: 'Claude Code',
    type: 'claude_code',
    installationStatus: 'Installed',
    version: 'v0.2.29',
    executable: '/usr/local/bin/claude',
    authenticationStatus: 'Authenticated',
    connectionStatus: 'Connected',
    lastVerifiedAt: '2026-08-08 12:00:00',
    capabilities: ['Code Generation', 'Architectural Planning', 'Refactoring', 'Bug Fixing'],
    description: 'Anthropic Claude Code CLI adapter for terminal-native agent execution.',
    iconName: 'Bot',
  },
  {
    id: 'openai-codex',
    name: 'OpenAI Codex',
    type: 'codex',
    installationStatus: 'Installed',
    version: 'v1.4.0',
    executable: '/usr/local/bin/codex',
    authenticationStatus: 'Authenticated',
    connectionStatus: 'Connected',
    lastVerifiedAt: '2026-08-08 11:45:00',
    capabilities: ['Code Completion', 'Test Generation', 'API Integration'],
    description: 'OpenAI Codex CLI adapter for automated code generation.',
    iconName: 'Cpu',
  },
  {
    id: 'google-antigravity',
    name: 'Google Antigravity',
    type: 'antigravity',
    installationStatus: 'Installed',
    version: 'v2.1.0',
    executable: '/usr/local/bin/agy',
    authenticationStatus: 'Authenticated',
    connectionStatus: 'Connected',
    lastVerifiedAt: '2026-08-08 10:30:00',
    capabilities: ['Multi-Agent Orchestration', 'Autonomous Refactoring', 'Verification'],
    description: 'Google Antigravity CLI adapter for advanced agentic workflow execution.',
    iconName: 'Zap',
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    type: 'openrouter',
    installationStatus: 'Installed',
    version: 'v0.8.1',
    executable: '/usr/local/bin/openrouter',
    authenticationStatus: 'Needs Authentication',
    connectionStatus: 'Disconnected',
    lastVerifiedAt: 'Never',
    capabilities: ['Multi-Model Routing', 'Fallback Execution', 'LLM Aggregation'],
    description: 'Unified OpenRouter API gateway adapter for model routing.',
    iconName: 'Globe',
  },
];

const SUGGESTIONS: Suggestion[] = [
  {
    id: 'rest-api',
    title: 'Build REST API',
    description: 'Design endpoints, request validation, and route handlers.',
    promptText: 'Design and build a high-performance REST API with request validation and route handlers.',
    iconName: 'Server',
  },
  {
    id: 'react-dashboard',
    title: 'Create React Dashboard',
    description: 'Build interactive charts, dark mode UI, and widgets.',
    promptText: 'Create an interactive React analytics dashboard with dark mode UI components.',
    iconName: 'LayoutDashboard',
  },
  {
    id: 'analyze-dataset',
    title: 'Analyze Dataset',
    description: 'Extract trends, statistics, and anomalies from tabular data.',
    promptText: 'Analyze dataset trends, summarize anomalies, and generate key statistical insights.',
    iconName: 'BarChart3',
  },
  {
    id: 'debug-python',
    title: 'Debug Python',
    description: 'Investigate failures, inspect stack traces, and propose fixes.',
    promptText: 'Investigate code failure, analyze stack trace, and propose a verified bug fix.',
    iconName: 'Bug',
  },
  {
    id: 'review-repository',
    title: 'Review Repository',
    description: 'Audit codebase for architecture, security, and performance.',
    promptText: 'Perform comprehensive code review for architecture, security vulnerabilities, and performance.',
    iconName: 'Code',
  },
  {
    id: 'generate-tests',
    title: 'Generate Tests',
    description: 'Draft unit and integration test suites with mock specifications.',
    promptText: 'Generate unit and integration test suites with comprehensive mock specifications.',
    iconName: 'CheckSquare',
  },
];

const KNOWLEDGE_DOCUMENTS: KnowledgeDocument[] = [
  {
    id: 'doc-workflow-engine',
    title: 'Workflow Engine Architecture',
    source: 'docs/architecture.md',
    tags: ['orchestration', 'state-machine', 'saga', 'backend'],
    lastUpdated: '2026-08-08 10:15:00',
    preview:
      'The Keystone Workflow Engine executes multi-step saga workflows across heterogeneous AI coding agents. It enforces strict finite state machine transitions and records every transition in a tamper-evident audit log.',
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
      'Central technology-agnostic TypeScript contract package defining common models for Agents, Workflows, Knowledge, and Extension IPC messaging.',
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
      'Multi-sprint architecture roadmap outlining Sprint 0 through Sprint 8 execution steps.',
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
      'FastAPI-powered Python service with SQLAlchemy ORM persistence and Pydantic schemas.',
    metadata: {
      author: 'Developer 1',
      version: 'v0.1.0',
      status: 'Stable',
      category: 'Backend Core',
      wordCount: 1750,
    },
  },
  {
    id: 'doc-retry-strategy',
    title: 'Resilience & Retry Strategy',
    source: 'backend/app/resilience/retry.py',
    tags: ['resilience', 'circuit-breaker', 'retry', 'fault-tolerance'],
    lastUpdated: '2026-08-05 11:20:00',
    preview:
      'Implements per-agent circuit breakers and exponential backoff retry policies.',
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
      'Orchestrates sequential step execution by dispatching tasks to registered agent subprocess runners.',
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
      'Registry mapping canonical agent types to verification routines and execution capability sets.',
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
      'Specification for the OpenRouter multi-model API adapter for cloud LLM fallbacks.',
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
      'Headless subprocess runner for Anthropic Claude Code CLI using local OS user authentication tokens.',
    metadata: {
      author: 'Developer 3',
      version: 'v0.2.29',
      status: 'Verified',
      category: 'Connectors',
      wordCount: 1050,
    },
  },
  {
    id: 'doc-vscode-extension',
    title: 'VS Code Extension Architecture',
    source: 'vscode-extension/README.md',
    tags: ['vscode', 'extension', 'webview', 'react', 'vite'],
    lastUpdated: '2026-08-08 12:00:00',
    preview:
      'Architecture guide for the Keystone VS Code Extension host and webview integration.',
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
      'Specification for indexing local Markdown Obsidian vaults and wikilink graph indexing.',
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
      'Complete REST API contract reference listing endpoints for workflows, agents, audit, and resilience.',
    metadata: {
      author: 'Developer 1',
      version: 'v0.2.0',
      status: 'Stable Contract',
      category: 'API Specifications',
      wordCount: 2450,
    },
  },
];

const EXECUTION_STAGES: StageDefinition[] = [
  {
    id: 'planner',
    title: 'Planner',
    description: 'Decomposes engineering tasks into structured execution steps.',
    iconName: 'Brain',
    durationMs: 1500,
    logs: [
      'Analyzing engineering task requirements...',
      'Decomposing prompt into step graph dependencies...',
      'Execution graph created successfully.',
    ],
  },
  {
    id: 'research',
    title: 'Research',
    description: 'Gathers context, codebase references, and dependency definitions.',
    iconName: 'Search',
    durationMs: 1800,
    logs: [
      'Searching documentation and codebase indices...',
      'Inspecting project symbols and interface contracts...',
      'Dependencies and context references resolved.',
    ],
  },
  {
    id: 'executor',
    title: 'Executor',
    description: 'Executes task steps through assigned AI coding agents.',
    iconName: 'Play',
    durationMs: 2200,
    logs: [
      'Generating implementation plan across agent workers...',
      'Executing code generation tasks via CLI connector...',
      'Code execution artifacts produced.',
    ],
  },
  {
    id: 'validator',
    title: 'Validator',
    description: 'Runs test suites, static analysis, and type verification.',
    iconName: 'ShieldCheck',
    durationMs: 1600,
    logs: [
      'Running automated static analysis check...',
      'Verifying TypeScript type declarations and build rules...',
      'Validation suite passed with zero errors.',
    ],
  },
  {
    id: 'reporter',
    title: 'Reporter',
    description: 'Compiles execution outputs and tamper-evident audit logs.',
    iconName: 'FileText',
    durationMs: 1200,
    logs: [
      'Hashing execution state into cryptographic audit log chain...',
      'Compiling final execution summary report...',
      'Workflow completed successfully.',
    ],
  },
];

const FALLBACK_WORKSPACE_TREE: WorkspaceNodeItem[] = [
  {
    id: '.',
    name: 'Keystone',
    relativePath: '.',
    kind: 'directory',
    lastModified: '2026-08-08 12:00:00',
    children: [
      {
        id: 'backend',
        name: 'backend',
        relativePath: 'backend',
        kind: 'directory',
        lastModified: '2026-08-08 11:30:00',
        children: [
          {
            id: 'backend/app/main.py',
            name: 'main.py',
            relativePath: 'backend/app/main.py',
            kind: 'file',
            size: 1420,
            extension: '.py',
            lastModified: '2026-08-08 10:45:00',
            preview: 'from fastapi import FastAPI\napp = FastAPI(title="Keystone Engine")',
          },
        ],
      },
      {
        id: 'frontend',
        name: 'frontend',
        relativePath: 'frontend',
        kind: 'directory',
        lastModified: '2026-08-08 10:00:00',
        children: [
          {
            id: 'frontend/package.json',
            name: 'package.json',
            relativePath: 'frontend/package.json',
            kind: 'file',
            size: 890,
            extension: '.json',
            lastModified: '2026-08-08 09:15:00',
            preview: '{\n  "name": "keystone-web-frontend"\n}',
          },
        ],
      },
      {
        id: 'shared-contracts',
        name: 'shared-contracts',
        relativePath: 'shared-contracts',
        kind: 'directory',
        lastModified: '2026-08-08 08:30:00',
        children: [
          {
            id: 'shared-contracts/src/index.ts',
            name: 'index.ts',
            relativePath: 'shared-contracts/src/index.ts',
            kind: 'file',
            size: 640,
            extension: '.ts',
            lastModified: '2026-08-08 07:50:00',
            preview: 'export * from "./agents";\nexport * from "./workflows";',
          },
        ],
      },
      {
        id: 'vscode-extension',
        name: 'vscode-extension',
        relativePath: 'vscode-extension',
        kind: 'directory',
        lastModified: '2026-08-08 12:30:00',
        children: [
          {
            id: 'vscode-extension/package.json',
            name: 'package.json',
            relativePath: 'vscode-extension/package.json',
            kind: 'file',
            size: 1650,
            extension: '.json',
            lastModified: '2026-08-08 12:00:00',
            preview: '{\n  "name": "keystone-vscode-extension"\n}',
          },
        ],
      },
      {
        id: 'README.md',
        name: 'README.md',
        relativePath: 'README.md',
        kind: 'file',
        size: 2850,
        extension: '.md',
        lastModified: '2026-08-08 12:45:00',
        preview: '# Keystone — AI Agent Orchestration Platform',
      },
    ],
  },
];

/**
 * Mock Data Provider exposing async methods for the API Layer.
 */
export class MockProvider {
  private static agentsState: AgentItem[] = [...INITIAL_AGENTS];

  public static async getSuggestions(): Promise<Suggestion[]> {
    return Promise.resolve([...SUGGESTIONS]);
  }

  public static async getExecutionStages(): Promise<StageDefinition[]> {
    return Promise.resolve([...EXECUTION_STAGES]);
  }

  public static async getAgents(): Promise<AgentItem[]> {
    return Promise.resolve([...this.agentsState]);
  }

  public static async verifyAgent(agentId: string): Promise<AgentItem> {
    const now = new Date();
    const formattedDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(
      2,
      '0'
    )}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(
      2,
      '0'
    )}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(
      2,
      '0'
    )}`;

    this.agentsState = this.agentsState.map((agent) => {
      if (agent.id === agentId) {
        return {
          ...agent,
          connectionStatus: 'Connected',
          authenticationStatus: 'Authenticated',
          lastVerifiedAt: formattedDate,
        };
      }
      return agent;
    });

    const updated = this.agentsState.find((a) => a.id === agentId);
    if (!updated) throw new Error(`Agent ${agentId} not found`);
    return Promise.resolve({ ...updated });
  }

  public static async getKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
    return Promise.resolve([...KNOWLEDGE_DOCUMENTS]);
  }

  public static async getWorkspaceTree(): Promise<WorkspaceNodeItem[]> {
    return Promise.resolve([...FALLBACK_WORKSPACE_TREE]);
  }
}
