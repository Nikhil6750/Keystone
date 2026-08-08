import React from 'react';
import { SuggestionCard } from './SuggestionCard';
import type { Suggestion } from '../../api/MockProvider';

interface SuggestionGridProps {
  suggestions?: Suggestion[];
  selectedTemplate: string | null;
  onSelectSuggestion: (suggestion: Suggestion) => void;
}

export const SuggestionGrid: React.FC<SuggestionGridProps> = ({
  suggestions = [],
  selectedTemplate,
  onSelectSuggestion,
}) => {
  return (
    <div className="suggestion-grid-wrapper">
      <span className="section-title">Prompt Suggestions</span>
      <div className="suggestion-grid">
        {suggestions.map((suggestion) => (
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
