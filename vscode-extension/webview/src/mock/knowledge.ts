import { MockProvider, type KnowledgeDocument } from '../api/MockProvider';

export type { KnowledgeDocument };

export let MOCK_KNOWLEDGE_DOCUMENTS: KnowledgeDocument[] = [];
MockProvider.getKnowledgeDocuments().then((docs) => {
  MOCK_KNOWLEDGE_DOCUMENTS = docs;
});
