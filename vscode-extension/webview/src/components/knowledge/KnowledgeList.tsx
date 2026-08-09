import React from 'react';
import { KnowledgeCard } from './KnowledgeCard';
import type { KnowledgeDocument } from '../../mock/knowledge';
import { BookOpen } from 'lucide-react';

interface KnowledgeListProps {
  documents: KnowledgeDocument[];
  selectedDocumentId: string | null;
  onSelectDocument: (docId: string) => void;
}

export const KnowledgeList: React.FC<KnowledgeListProps> = ({
  documents,
  selectedDocumentId,
  onSelectDocument,
}) => {
  if (documents.length === 0) {
    return (
      <div className="agent-empty-state">
        <BookOpen size={32} className="empty-icon" />
        <p className="empty-title">No knowledge documents found</p>
        <p className="empty-subtitle">Try adjusting your search query or tags filter.</p>
      </div>
    );
  }

  return (
    <div className="agent-grid">
      {documents.map((doc) => (
        <KnowledgeCard
          key={doc.id}
          document={doc}
          isSelected={selectedDocumentId === doc.id}
          onSelect={onSelectDocument}
        />
      ))}
    </div>
  );
};
