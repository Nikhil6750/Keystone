/**
 * Document indexed within the Keystone Knowledge store.
 */
export interface KnowledgeDocument {
  id: string;
  title: string;
  content: string;
  source?: string;
  tags?: string[];
  createdAt?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Result object returned from a Knowledge search query.
 */
export interface KnowledgeSearchResult {
  document: KnowledgeDocument;
  score: number;
  snippet?: string;
}
