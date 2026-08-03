export interface WorkflowItem {
  id: string;
  name: string;
  status: 'Waiting' | 'Running' | 'Completed' | 'Failed';
  currentStage: string;
  createdBy: string;
  duration: string;
  lastUpdated: string;
}

export interface AgentModel {
  id: string;
  name: string;
  badge: 'Waiting' | 'Active' | 'Idle' | 'Offline';
  dotBg: string;
  description: string;
  type: string;
  capabilities: string;
  tools: string;
  version: string;
  lastSeen: string;
}

export interface WorkflowStage {
  name: string;
  badge: string;
  description: string;
  iconBg?: string;
  dotBg?: string;
}

export interface SystemLogEntry {
  id: string;
  timestamp: string;
  level: 'INFO' | 'DEBUG' | 'WARN' | 'ERROR';
  levelBg: string;
  source: string;
  workflow: string;
  message: string;
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  content: string;
  timestamp: string;
  stage?: string;
}

export interface NotificationItem {
  id: string;
  title: string;
  description: string;
  timestamp: string;
  read: boolean;
  type: 'info' | 'success' | 'warning' | 'error';
}

export interface UserSettings {
  autoSave: boolean;
  confirmDestructive: boolean;
  enableTelemetry: boolean;
  language: string;
  timeZone: string;
  dateFormat: string;
}
