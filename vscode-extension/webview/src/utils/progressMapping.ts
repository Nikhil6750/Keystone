import type { OrchestrationEvent } from '../types/keystone';

export interface ProgressLine {
  id: string;
  text: string;
  kind: 'info' | 'agent' | 'success' | 'error';
}

/**
 * Maps one safe `OrchestrationEvent` into at most one short, human-readable
 * progress line. Never renders a raw event, its `data`, or any field this
 * module does not explicitly name below -- only `agent_id`, `task_key`,
 * and a small set of already-safe, already-parsed `message` shapes
 * (`task_count=N`) ever reach the UI. Returns `null` for events that are
 * meaningful for sequencing/telemetry but not worth a visible line (e.g.
 * `knowledge.started`), and for the terminal events, which are rendered by
 * `ExecutionResult` instead of the progress list.
 */
export function mapEventToProgressLine(event: OrchestrationEvent): ProgressLine | null {
  switch (event.event_type) {
    case 'execution.started':
      return { id: event.event_id, text: 'Understanding goal...', kind: 'info' };

    case 'manager.fallback':
      return {
        id: event.event_id,
        text: 'Using deterministic planning fallback...',
        kind: 'info',
      };

    case 'planning.completed': {
      const taskCount = parseTaskCount(event.message);
      return {
        id: event.event_id,
        text:
          taskCount !== null
            ? `Planning ${taskCount} task${taskCount === 1 ? '' : 's'}...`
            : 'Planning...',
        kind: 'info',
      };
    }

    case 'routing.failed':
      return { id: event.event_id, text: 'No eligible agent found for this task.', kind: 'error' };

    case 'step.started':
      return event.agent_id
        ? {
            id: event.event_id,
            text: `${event.agent_id} — working${event.task_key ? ` on ${event.task_key}` : ''}`,
            kind: 'agent',
          }
        : null;

    case 'step.completed':
      return event.agent_id
        ? {
            id: event.event_id,
            text: `${event.agent_id} — done${event.task_key ? ` with ${event.task_key}` : ''}`,
            kind: 'agent',
          }
        : null;

    case 'step.failed':
      return event.agent_id
        ? {
            id: event.event_id,
            text: `${event.agent_id} — hit an issue${event.task_key ? ` on ${event.task_key}` : ''}`,
            kind: 'error',
          }
        : null;

    case 'verification.started':
      return { id: event.event_id, text: 'Verifying...', kind: 'info' };

    case 'recovery.started':
      return {
        id: event.event_id,
        text: 'Retrying to reach a verified result...',
        kind: 'info',
      };

    case 'recovery.exhausted':
      return {
        id: event.event_id,
        text: 'Unable to reach a verified result after retries.',
        kind: 'error',
      };

    case 'execution.cancelled':
      return { id: event.event_id, text: 'Execution cancelled.', kind: 'error' };

    default:
      return null;
  }
}

function parseTaskCount(message: string | null): number | null {
  if (!message) return null;
  const match = /^task_count=(\d+)$/.exec(message);
  return match ? Number(match[1]) : null;
}
