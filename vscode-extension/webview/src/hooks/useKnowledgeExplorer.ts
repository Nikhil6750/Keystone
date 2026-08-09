import { useState, useEffect, useMemo } from 'react';
import { KnowledgeService } from '../services/KnowledgeService';
import type { KnowledgeDocument } from '../api/MockProvider';
import { useAppState } from './useAppState';

export function useKnowledgeExplorer() {
  const { selectedKnowledgeId, setSelectedKnowledgeId } = useAppState();
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>('');

  useEffect(() => {
    let isMounted = true;
    KnowledgeService.listDocuments().then((docs) => {
      if (isMounted) setDocuments(docs);
    });
    return () => {
      isMounted = false;
    };
  }, []);

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
