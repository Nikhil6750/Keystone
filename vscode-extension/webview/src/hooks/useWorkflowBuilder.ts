import { useState, useCallback } from 'react';

export interface Suggestion {
  id: string;
  title: string;
  description: string;
  promptText: string;
  iconName: string;
}

export const SUGGESTIONS: Suggestion[] = [
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

export function useWorkflowBuilder() {
  const [prompt, setPrompt] = useState<string>('');
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const selectSuggestion = useCallback((suggestion: Suggestion) => {
    setPrompt(suggestion.promptText);
    setSelectedTemplate(suggestion.id);
  }, []);

  const handleExecute = useCallback(() => {
    setToastMessage(
      'Workflow execution is not available yet. Backend integration will be added in a future sprint.'
    );
  }, []);

  const dismissToast = useCallback(() => {
    setToastMessage(null);
  }, []);

  const reset = useCallback(() => {
    setPrompt('');
    setSelectedTemplate(null);
    setToastMessage(null);
  }, []);

  return {
    prompt,
    setPrompt,
    selectedTemplate,
    selectSuggestion,
    handleExecute,
    toastMessage,
    dismissToast,
    reset,
  };
}
