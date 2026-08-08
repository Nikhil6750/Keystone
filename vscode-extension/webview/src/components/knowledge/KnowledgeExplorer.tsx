import React from 'react';
import { KnowledgeSearch } from './KnowledgeSearch';
import { KnowledgeList } from './KnowledgeList';
import { KnowledgeDetails } from './KnowledgeDetails';
import { useKnowledgeExplorer } from '../../hooks/useKnowledgeExplorer';

export const KnowledgeExplorer: React.FC = () => {
  const {
    searchQuery,
    setSearchQuery,
    selectedDocument,
    setSelectedDocumentId,
    filteredDocuments,
  } = useKnowledgeExplorer();

  return (
    <div className="agent-manager-container">
      <header className="builder-header">
        <h1 className="builder-title">Knowledge Explorer</h1>
        <p className="builder-subtitle">
          Explore indexed architectural specifications, documentation, and experience memory.
        </p>
      </header>

      <KnowledgeSearch value={searchQuery} onChange={setSearchQuery} />

      <KnowledgeList
        documents={filteredDocuments}
        selectedDocumentId={selectedDocument?.id || null}
        onSelectDocument={(id) => setSelectedDocumentId(id)}
      />

      <KnowledgeDetails
        document={selectedDocument}
        onClose={() => setSelectedDocumentId(null)}
      />
    </div>
  );
};
