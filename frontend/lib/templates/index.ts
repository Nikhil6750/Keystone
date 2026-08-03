/**
 * Static, locally-defined workflow templates. These are honest editable
 * starting points, never dynamically generated, learned, personalized, or
 * produced by a manager agent — the user must review and confirm every
 * field before a workflow is created. See `docs/phase5-integration.md`.
 */

export interface WorkflowTemplateStep {
  name: string;
  agentType: string;
  maxAttempts: number;
}

export interface WorkflowTemplate {
  id: string;
  title: string;
  description: string;
  workflowName: string;
  workflowDescription: string;
  inputPayloadText: string;
  steps: WorkflowTemplateStep[];
}

export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'rest-api',
    title: 'Build REST API',
    description: 'Design endpoints, request models, validation, and route handlers.',
    workflowName: 'Build REST API',
    workflowDescription: 'Design and implement a REST API with validated request handling.',
    inputPayloadText: '{\n  "framework": "FastAPI"\n}',
    steps: [
      { name: 'design-endpoints', agentType: 'demo', maxAttempts: 3 },
      { name: 'implement-handlers', agentType: 'demo', maxAttempts: 3 },
    ],
  },
  {
    id: 'ml-pipeline',
    title: 'Create ML Pipeline',
    description: 'Outline data preparation, training, and evaluation steps.',
    workflowName: 'Create ML Pipeline',
    workflowDescription: 'Draft a machine-learning pipeline from data prep through evaluation.',
    inputPayloadText: '{\n  "dataset": "unspecified"\n}',
    steps: [
      { name: 'prepare-data', agentType: 'demo', maxAttempts: 3 },
      { name: 'train-model', agentType: 'demo', maxAttempts: 3 },
      { name: 'evaluate-model', agentType: 'demo', maxAttempts: 3 },
    ],
  },
  {
    id: 'analyze-csv',
    title: 'Analyze CSV Dataset',
    description: 'Extract insights and generate a summary report from tabular data.',
    workflowName: 'Analyze CSV Dataset',
    workflowDescription: 'Summarize trends and anomalies in a CSV dataset.',
    inputPayloadText: '{\n  "file_hint": "data.csv"\n}',
    steps: [{ name: 'analyze-dataset', agentType: 'demo', maxAttempts: 3 }],
  },
  {
    id: 'debug-python',
    title: 'Debug Python Code',
    description: 'Find issues and suggest fixes in an existing Python codebase.',
    workflowName: 'Debug Python Code',
    workflowDescription: 'Investigate a failure and propose a fix.',
    inputPayloadText: '{\n  "context": "describe the failure here"\n}',
    steps: [{ name: 'debug-code', agentType: 'demo', maxAttempts: 3 }],
  },
  {
    id: 'review-react',
    title: 'Review React Project',
    description: 'Inspect component architecture, state management, and performance.',
    workflowName: 'Review React Project',
    workflowDescription: 'Review a React project for structure and performance issues.',
    inputPayloadText: '{}',
    steps: [{ name: 'review-project', agentType: 'demo', maxAttempts: 3 }],
  },
  {
    id: 'generate-tests',
    title: 'Generate Unit Tests',
    description: 'Draft automated test suites and mock specifications.',
    workflowName: 'Generate Unit Tests',
    workflowDescription: 'Draft unit and integration tests for a target module.',
    inputPayloadText: '{}',
    steps: [{ name: 'generate-tests', agentType: 'demo', maxAttempts: 3 }],
  },
];
