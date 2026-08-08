import React from 'react';
import { SuggestionCard } from './SuggestionCard';
import { SUGGESTIONS, type Suggestion } from '../../hooks/useWorkflowBuilder';

interface SuggestionGridProps {
  selectedTemplate: string | null;
  onSelectSuggestion: (suggestion: Suggestion) => void;
}

export const SuggestionGrid: React.FC<SuggestionGridProps> = ({
  selectedTemplate,
  onSelectSuggestion,
}) => {
  return (
    <div className="suggestion-grid-wrapper">
      <span className="section-title">Prompt Suggestions</span>
      <div className="suggestion-grid">
        {SUGGESTIONS.map((suggestion) => (
          <SuggestionCard
            key={suggestion.id}
            suggestion={suggestion}
            isSelected={selectedTemplate === suggestion.id}
            onSelect={onSelectSuggestion}
          />
        ))}
      </div>
    </div>
  );
};
