import { ApiClient } from './ApiClient';
import type { KnowledgeDocument } from './MockProvider';

export class KnowledgeApi {
  public static async fetchKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
    const res = await ApiClient.get<KnowledgeDocument[]>('/knowledge');
    return res.data;
  }
}
