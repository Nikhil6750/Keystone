export const APP_CONFIG = {
  name: 'Keystone AI',
  description: 'Adaptive Multi-Agent AI Orchestration Platform',
  apiBaseUrl: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  githubUrl: 'https://github.com/Nikhil6750/Keystone',
  defaultTheme: 'dark',
} as const;

export const ROUTES = {
  home: '/',
  chat: '/chat',
  workflows: '/workflows',
  agents: '/agents',
  logs: '/logs',
  settings: '/settings',
} as const;
