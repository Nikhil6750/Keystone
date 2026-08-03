/**
 * Purely local, UI-only types — never a stand-in for a backend resource.
 * Workflow/agent/audit-event data always comes from `./backend.ts` types
 * populated from real API responses instead.
 */

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface NotificationItem {
  id: string;
  title: string;
  description: string;
  timestamp: string;
  read: boolean;
  type: 'info' | 'success' | 'warning' | 'error';
}
