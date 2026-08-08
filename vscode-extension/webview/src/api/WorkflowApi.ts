import { ApiClient } from './ApiClient';
import type { Suggestion, StageDefinition } from './MockProvider';

export class WorkflowApi {
  public static async fetchSuggestions(): Promise<Suggestion[]> {
    const res = await ApiClient.get<Suggestion[]>('/workflow/suggestions');
    return res.data;
  }

  public static async fetchExecutionStages(): Promise<StageDefinition[]> {
    const res = await ApiClient.get<StageDefinition[]>('/workflow/stages');
    return res.data;
  }
}
