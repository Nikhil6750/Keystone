/**
 * The Keystone FastAPI backend base URL, with any trailing slash removed so
 * every caller can safely append a leading-slash path. `http://localhost:8000`
 * is a development-only fallback, used only when `NEXT_PUBLIC_API_URL` is unset.
 */
function resolveApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  return raw.replace(/\/+$/, '');
}

export const APP_CONFIG = {
  name: 'Keystone AI',
  version: '0.1.0',
  description: 'Adaptive Multi-Agent AI Orchestration Platform',
  apiBaseUrl: resolveApiBaseUrl(),
  githubUrl: 'https://github.com/Nikhil6750/Keystone',
  defaultTheme: 'dark',
  prototypePhase: 'Phase 5: Frontend integration prototype',
} as const;

export const ROUTES = {
  home: '/',
  chat: '/chat',
  workflows: '/workflows',
  agents: '/agents',
  logs: '/logs',
  settings: '/settings',
} as const;

/** Canonical agent types the backend recognizes (see `docs/api-contract.md`). */
export const CANONICAL_AGENT_TYPES = ['claude_code', 'codex', 'gemini', 'demo'] as const;
