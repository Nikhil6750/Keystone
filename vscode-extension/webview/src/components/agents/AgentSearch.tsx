import React from 'react';
import { Search, X } from 'lucide-react';

interface AgentSearchProps {
  value: string;
  onChange: (value: string) => void;
}

export const AgentSearch: React.FC<AgentSearchProps> = ({ value, onChange }) => {
  return (
    <div className="agent-search-wrapper">
      <Search size={16} className="search-icon" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Filter agents by name, type, or capability..."
        className="agent-search-input"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          className="search-clear-btn"
          aria-label="Clear search"
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
};
