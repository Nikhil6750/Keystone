import { SystemLogEntry } from '@/types';

export const INITIAL_LOGS: SystemLogEntry[] = [
  {
    id: '1',
    timestamp: 'May 24, 2025 10:42:31',
    level: 'INFO',
    levelBg: 'bg-emerald-950/60 border-emerald-500/30 text-emerald-400',
    source: 'planner-agent',
    workflow: '-',
    message: 'Planner agent initialized successfully',
  },
  {
    id: '2',
    timestamp: 'May 24, 2025 10:42:28',
    level: 'INFO',
    levelBg: 'bg-emerald-950/60 border-emerald-500/30 text-emerald-400',
    source: 'system',
    workflow: '-',
    message: 'System startup completed in 1.2s',
  },
  {
    id: '3',
    timestamp: 'May 24, 2025 10:42:25',
    level: 'DEBUG',
    levelBg: 'bg-blue-950/60 border-blue-500/30 text-blue-400',
    source: 'api-server',
    workflow: '-',
    message: 'API server listening on port 8000',
  },
  {
    id: '4',
    timestamp: 'May 24, 2025 10:42:20',
    level: 'INFO',
    levelBg: 'bg-emerald-950/60 border-emerald-500/30 text-emerald-400',
    source: 'auth-service',
    workflow: '-',
    message: 'Authentication service connected',
  },
  {
    id: '5',
    timestamp: 'May 24, 2025 10:41:15',
    level: 'WARN',
    levelBg: 'bg-amber-950/60 border-amber-500/30 text-amber-400',
    source: 'executor-agent',
    workflow: 'wf_8f3a2c',
    message: 'Execution timeout threshold high (120s)',
  },
  {
    id: '6',
    timestamp: 'May 24, 2025 10:40:58',
    level: 'ERROR',
    levelBg: 'bg-rose-950/60 border-rose-500/30 text-rose-400',
    source: 'validator-agent',
    workflow: 'wf_7c9b1f',
    message: 'Validation failed: Output schema mismatch',
  },
  {
    id: '7',
    timestamp: 'May 24, 2025 10:40:52',
    level: 'INFO',
    levelBg: 'bg-emerald-950/60 border-emerald-500/30 text-emerald-400',
    source: 'research-agent',
    workflow: 'wf_7c9b1f',
    message: 'Research completed with 12 sources',
  },
  {
    id: '8',
    timestamp: 'May 24, 2025 10:40:40',
    level: 'INFO',
    levelBg: 'bg-emerald-950/60 border-emerald-500/30 text-emerald-400',
    source: 'workflow-engine',
    workflow: 'wf_7c9b1f',
    message: 'Workflow execution started',
  },
  {
    id: '9',
    timestamp: 'May 24, 2025 10:40:39',
    level: 'DEBUG',
    levelBg: 'bg-blue-950/60 border-blue-500/30 text-blue-400',
    source: 'db-connector',
    workflow: '-',
    message: 'Database connection pool active',
  },
  {
    id: '10',
    timestamp: 'May 24, 2025 10:40:30',
    level: 'INFO',
    levelBg: 'bg-emerald-950/60 border-emerald-500/30 text-emerald-400',
    source: 'agent-registry',
    workflow: '-',
    message: '5 agents registered successfully',
  },
];

export function generateMockLog(): SystemLogEntry {
  const sources = [
    'planner-agent',
    'executor-agent',
    'research-agent',
    'validator-agent',
    'system',
  ];
  const levels: Array<'INFO' | 'DEBUG' | 'WARN'> = ['INFO', 'DEBUG', 'WARN'];
  const messages = [
    'Telemetry ping received',
    'Agent state heartbeating',
    'Context buffer refreshed',
    'Schema validation check passed',
    'Execution queue tick processed',
  ];

  const source = sources[Math.floor(Math.random() * sources.length)];
  const level = levels[Math.floor(Math.random() * levels.length)];
  const message = messages[Math.floor(Math.random() * messages.length)];

  const levelBgMap = {
    INFO: 'bg-emerald-950/60 border-emerald-500/30 text-emerald-400',
    DEBUG: 'bg-blue-950/60 border-blue-500/30 text-blue-400',
    WARN: 'bg-amber-950/60 border-amber-500/30 text-amber-400',
  };

  return {
    id: `log-${Date.now()}`,
    timestamp: new Date().toLocaleString('en-US', {
      month: 'short',
      day: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }),
    level,
    levelBg: levelBgMap[level],
    source,
    workflow: '-',
    message,
  };
}
