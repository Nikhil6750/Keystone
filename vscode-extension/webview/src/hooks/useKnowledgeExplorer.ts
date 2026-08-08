import { useState, useMemo } from 'react';
import {
  MOCK_KNOWLEDGE_DOCUMENTS,
  type KnowledgeDocument,
} from '../mock/knowledge';

export function useKnowledgeExplorer() {
  const [documents] = useState<KnowledgeDocument[]>(MOCK_KNOWLEDGE_DOCUMENTS);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(
    null
  );

  const selectedDocument = useMemo(
    () => documents.find((doc) => doc.id === selectedDocumentId) || null,
    [documents, selectedDocumentId]
  );

  const filteredDocuments = useMemo(() => {
    if (!searchQuery.trim()) return documents;
    const query = searchQuery.toLowerCase().trim();
    return documents.filter(
      (doc) =>
        doc.title.toLowerCase().includes(query) ||
        doc.source.toLowerCase().includes(query) ||
        doc.tags.some((tag) => tag.toLowerCase().includes(query))
    );
  }, [documents, searchQuery]);

  return {
    searchQuery,
    setSearchQuery,
    selectedDocument,
    setSelectedDocumentId,
    filteredDocuments,
  };
}
