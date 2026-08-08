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

export const INITIAL_AGENTS: AgentItem[] = [
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
