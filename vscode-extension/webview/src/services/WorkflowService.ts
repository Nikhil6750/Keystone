import { WorkflowApi } from '../api/WorkflowApi';
import type { Suggestion, StageDefinition } from '../api/MockProvider';

export class WorkflowService {
  public static async getTemplates(): Promise<Suggestion[]> {
    return WorkflowApi.fetchSuggestions();
  }

  public static async getExecutionStages(): Promise<StageDefinition[]> {
    return WorkflowApi.fetchExecutionStages();
  }
}
