import { useState, useEffect, useCallback } from 'react';
import { WorkflowService } from '../services/WorkflowService';
import type { Suggestion } from '../api/MockProvider';
import { useAppState } from './useAppState';

export type { Suggestion };

export function useWorkflowBuilder() {
  const {
    prompt,
    setPrompt,
    selectedTemplate,
    setSelectedTemplate,
    pushNotification,
  } = useAppState();

  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);

  useEffect(() => {
    let isMounted = true;
    WorkflowService.getTemplates().then((items) => {
      if (isMounted) setSuggestions(items);
    });
    return () => {
      isMounted = false;
    };
  }, []);

  const selectSuggestion = useCallback(
    (suggestion: Suggestion) => {
      setPrompt(suggestion.promptText);
      setSelectedTemplate(suggestion.id);
    },
    [setPrompt, setSelectedTemplate]
  );

  const reset = useCallback(() => {
    setPrompt('');
    setSelectedTemplate(null);
  }, [setPrompt, setSelectedTemplate]);

  return {
    prompt,
    setPrompt,
    selectedTemplate,
    suggestions,
    selectSuggestion,
    pushNotification,
    reset,
  };
}
