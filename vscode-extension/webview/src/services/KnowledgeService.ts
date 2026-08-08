import { KnowledgeApi } from '../api/KnowledgeApi';
import type { KnowledgeDocument } from '../api/MockProvider';

export class KnowledgeService {
  public static async listDocuments(): Promise<KnowledgeDocument[]> {
    return KnowledgeApi.fetchKnowledgeDocuments();
  }

  public static async search(query: string): Promise<KnowledgeDocument[]> {
    const docs = await KnowledgeApi.fetchKnowledgeDocuments();
    if (!query.trim()) return docs;
    const q = query.toLowerCase().trim();
    return docs.filter(
      (doc) =>
        doc.title.toLowerCase().includes(q) ||
        doc.source.toLowerCase().includes(q) ||
        doc.tags.some((tag) => tag.toLowerCase().includes(q))
    );
  }

  public static async getDocument(id: string): Promise<KnowledgeDocument | null> {
    const docs = await KnowledgeApi.fetchKnowledgeDocuments();
    return docs.find((d) => d.id === id) || null;
  }
}
