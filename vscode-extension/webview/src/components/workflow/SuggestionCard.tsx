import React from 'react';
import {
  Server,
  LayoutDashboard,
  BarChart3,
  Bug,
  Code,
  CheckSquare,
  Sparkles,
} from 'lucide-react';
import type { Suggestion } from '../../api/MockProvider';

const ICON_MAP: Record<string, React.ElementType> = {
  Server,
  LayoutDashboard,
  BarChart3,
  Bug,
  Code,
  CheckSquare,
};

interface SuggestionCardProps {
  suggestion: Suggestion;
  isSelected: boolean;
  onSelect: (suggestion: Suggestion) => void;
}

export const SuggestionCard: React.FC<SuggestionCardProps> = ({
  suggestion,
  isSelected,
  onSelect,
}) => {
  const IconComponent = ICON_MAP[suggestion.iconName] || Sparkles;

  return (
    <button
      type="button"
      className={`suggestion-card ${isSelected ? 'selected' : ''}`}
      onClick={() => onSelect(suggestion)}
      aria-label={`Select template: ${suggestion.title}`}
    >
      <div className="card-header">
        <div className="icon-badge">
          <IconComponent size={16} />
        </div>
        <span className="card-title">{suggestion.title}</span>
      </div>
      <p className="card-description">{suggestion.description}</p>
    </button>
  );
};
