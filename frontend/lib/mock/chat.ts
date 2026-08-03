import { ChatMessage } from '@/types';

export const INITIAL_CHAT_MESSAGES: ChatMessage[] = [];

export function generateAssistantResponse(userPrompt: string): ChatMessage {
  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return {
    id: `msg-${Date.now()}`,
    sender: 'assistant',
    content: `I've analyzed your goal: "${userPrompt}". I have initialized the multi-agent pipeline (Planner → Research → Executor → Validator → Reporter) to orchestrate this task.`,
    timestamp,
    stage: 'Planner',
  };
}
