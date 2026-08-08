import React from 'react';
import { Search, X } from 'lucide-react';

interface KnowledgeSearchProps {
  value: string;
  onChange: (value: string) => void;
}

export const KnowledgeSearch: React.FC<KnowledgeSearchProps> = ({
  value,
  onChange,
}) => {
  return (
    <div className="agent-search-wrapper">
      <Search size={16} className="search-icon" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search documents by title, source path, or tags..."
        className="agent-search-input"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          className="search-clear-btn"
          aria-label="Clear knowledge search"
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
};
