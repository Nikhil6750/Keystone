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

export const EXECUTION_STAGES: StageDefinition[] = [
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
