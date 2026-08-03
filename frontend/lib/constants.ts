export const APP_CONFIG = {
  name: 'Keystone AI',
  description: 'Production AI SaaS Platform and Analytics Dashboard',
  apiBaseUrl: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  defaultTheme: 'dark',
} as const;

export const ROUTES = {
  home: '/',
  dashboard: '/dashboard',
  analytics: '/analytics',
  settings: '/settings',
} as const;
