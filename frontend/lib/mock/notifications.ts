import { NotificationItem } from '@/types';

export const INITIAL_NOTIFICATIONS: NotificationItem[] = [
  {
    id: 'n1',
    title: 'System Startup',
    description: 'Keystone multi-agent orchestrator started successfully.',
    timestamp: '10m ago',
    read: false,
    type: 'info',
  },
  {
    id: 'n2',
    title: 'Agent Fleet Active',
    description: '5 system agents (Planner, Research, Executor, Validator, Reporter) registered.',
    timestamp: '25m ago',
    read: false,
    type: 'success',
  },
  {
    id: 'n3',
    title: 'Database Pool',
    description: 'Database connection pool initialized.',
    timestamp: '1h ago',
    read: true,
    type: 'info',
  },
];
