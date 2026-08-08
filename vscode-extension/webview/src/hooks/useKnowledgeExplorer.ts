import { useState, useMemo } from 'react';
import {
  MOCK_KNOWLEDGE_DOCUMENTS,
  type KnowledgeDocument,
} from '../mock/knowledge';
import { useAppState } from './useAppState';

export function useKnowledgeExplorer() {
  const { selectedKnowledgeId, setSelectedKnowledgeId } = useAppState();
  const [documents] = useState<KnowledgeDocument[]>(MOCK_KNOWLEDGE_DOCUMENTS);
  const [searchQuery, setSearchQuery] = useState<string>('');

  const selectedDocument = useMemo(
    () => documents.find((doc) => doc.id === selectedKnowledgeId) || null,
    [documents, selectedKnowledgeId]
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
    setSelectedDocumentId: setSelectedKnowledgeId,
    filteredDocuments,
  };
}
