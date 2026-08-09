/**
 * Operational status of an agent within the Keystone system.
 */
export type AgentStatus =
  | 'idle'
  | 'busy'
  | 'connected'
  | 'disconnected'
  | 'unauthenticated'
  | 'error'
  | 'unavailable';

/**
 * Capability or skill provided by an agent.
 */
export interface AgentCapability {
  id: string;
  name: string;
  description: string;
  parametersSchema?: Record<string, unknown>;
}

/**
 * Representation of an AI Agent instance.
 */
export interface Agent {
  id: string;
  name: string;
  type: string;
  version?: string;
  status: AgentStatus;
  capabilities: AgentCapability[];
  metadata?: Record<string, unknown>;
}
