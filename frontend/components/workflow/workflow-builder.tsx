'use client';

import * as React from 'react';
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import { useAgents } from '@/hooks/use-agents';
import type { AgentAvailabilityRead, WorkflowCreate } from '@/types/backend';

export interface DraftStep {
  key: string;
  name: string;
  agentType: string;
  inputPayloadText: string;
  maxAttempts: number;
  compensationHandler: string;
}

export interface WorkflowDraft {
  name: string;
  description: string;
  inputPayloadText: string;
  steps: DraftStep[];
}

let keySeed = 0;
function nextKey(): string {
  keySeed += 1;
  return `draft-step-${keySeed}-${Date.now()}`;
}

export function createEmptyStep(): DraftStep {
  return {
    key: nextKey(),
    name: '',
    agentType: '',
    inputPayloadText: '{}',
    maxAttempts: 3,
    compensationHandler: '',
  };
}

export function createEmptyDraft(): WorkflowDraft {
  return {
    name: '',
    description: '',
    inputPayloadText: '{}',
    steps: [createEmptyStep()],
  };
}

export interface WorkflowBuilderErrors {
  name?: string;
  inputPayload?: string;
  steps: Record<string, string | undefined>;
}

function validateJson(text: string): { value: Record<string, unknown> | null; error: string | null } {
  const trimmed = text.trim();
  if (trimmed.length === 0) return { value: {}, error: null };
  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return { value: null, error: 'Must be a JSON object, e.g. {"key": "value"}.' };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch {
    return { value: null, error: 'Invalid JSON.' };
  }
}

export function validateDraft(draft: WorkflowDraft): WorkflowBuilderErrors {
  const errors: WorkflowBuilderErrors = { steps: {} };
  if (!draft.name.trim()) {
    errors.name = 'Workflow name is required.';
  }
  if (validateJson(draft.inputPayloadText).error) {
    errors.inputPayload = validateJson(draft.inputPayloadText).error ?? undefined;
  }
  for (const step of draft.steps) {
    if (!step.name.trim()) {
      errors.steps[step.key] = 'Step name is required.';
      continue;
    }
    if (!step.agentType) {
      errors.steps[step.key] = 'Select an agent for this step.';
      continue;
    }
    if (step.maxAttempts < 1) {
      errors.steps[step.key] = 'Maximum attempts must be at least 1.';
      continue;
    }
    if (validateJson(step.inputPayloadText).error) {
      errors.steps[step.key] = `Step input: ${validateJson(step.inputPayloadText).error}`;
    }
  }
  return errors;
}

export function draftHasErrors(errors: WorkflowBuilderErrors): boolean {
  return Boolean(errors.name || errors.inputPayload || Object.values(errors.steps).some(Boolean));
}

/** Builds the exact `WorkflowCreate` payload the backend accepts — never
 * including client-only fields like `id`, `status`, or timestamps. */
export function draftToWorkflowCreate(draft: WorkflowDraft): WorkflowCreate {
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || null,
    input_payload: validateJson(draft.inputPayloadText).value ?? {},
    steps: draft.steps.map((step, index) => ({
      name: step.name.trim(),
      position: index,
      agent_type: step.agentType,
      input_payload: validateJson(step.inputPayloadText).value ?? {},
      max_attempts: step.maxAttempts,
      compensation_handler: step.compensationHandler.trim() || null,
    })),
  };
}

function agentBadge(agent: AgentAvailabilityRead | undefined): string {
  if (!agent) return 'Unknown agent';
  if (!agent.enabled) return 'Disabled';
  if (!agent.registered) return 'Not registered';
  if (!agent.available) return 'Unavailable';
  return 'Ready';
}

export interface WorkflowBuilderProps {
  draft: WorkflowDraft;
  onChange: (draft: WorkflowDraft) => void;
  errors: WorkflowBuilderErrors;
  disabled?: boolean;
}

export const WorkflowBuilder: React.FC<WorkflowBuilderProps> = ({
  draft,
  onChange,
  errors,
  disabled = false,
}) => {
  const { data: agentsResponse } = useAgents();
  const agents = React.useMemo(() => agentsResponse?.items ?? [], [agentsResponse]);
  const agentByType = React.useMemo(
    () => new Map(agents.map((agent) => [agent.agent_type, agent])),
    [agents]
  );
  const demoRegistered = agentByType.get('demo')?.registered ?? false;

  const updateStep = (key: string, patch: Partial<DraftStep>) => {
    onChange({
      ...draft,
      steps: draft.steps.map((step) => (step.key === key ? { ...step, ...patch } : step)),
    });
  };

  const addStep = () => {
    onChange({ ...draft, steps: [...draft.steps, createEmptyStep()] });
  };

  const removeStep = (key: string) => {
    onChange({ ...draft, steps: draft.steps.filter((step) => step.key !== key) });
  };

  const moveStep = (index: number, direction: -1 | 1) => {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= draft.steps.length) return;
    const nextSteps = [...draft.steps];
    const [moved] = nextSteps.splice(index, 1);
    nextSteps.splice(targetIndex, 0, moved);
    onChange({ ...draft, steps: nextSteps });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
        <div className="space-y-1.5">
          <label htmlFor="workflow-name" className="block text-xs font-medium text-zinc-400">
            Workflow name
          </label>
          <input
            id="workflow-name"
            type="text"
            value={draft.name}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
            disabled={disabled}
            aria-invalid={Boolean(errors.name)}
            aria-describedby={errors.name ? 'workflow-name-error' : undefined}
            className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white placeholder:text-zinc-500 focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
            placeholder="e.g. FastAPI backend build"
          />
          {errors.name && (
            <p id="workflow-name-error" className="text-xs text-rose-400" role="alert">
              {errors.name}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <label htmlFor="workflow-description" className="block text-xs font-medium text-zinc-400">
            Description (optional)
          </label>
          <textarea
            id="workflow-description"
            value={draft.description}
            onChange={(e) => onChange({ ...draft, description: e.target.value })}
            disabled={disabled}
            rows={2}
            className="w-full resize-none rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white placeholder:text-zinc-500 focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
            placeholder="What should this workflow accomplish?"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="workflow-input" className="block text-xs font-medium text-zinc-400">
            Workflow input (JSON)
          </label>
          <textarea
            id="workflow-input"
            value={draft.inputPayloadText}
            onChange={(e) => onChange({ ...draft, inputPayloadText: e.target.value })}
            disabled={disabled}
            rows={2}
            aria-invalid={Boolean(errors.inputPayload)}
            aria-describedby={errors.inputPayload ? 'workflow-input-error' : undefined}
            className="w-full resize-none rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 font-mono text-xs text-white placeholder:text-zinc-500 focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
            placeholder="{}"
          />
          {errors.inputPayload && (
            <p id="workflow-input-error" className="text-xs text-rose-400" role="alert">
              {errors.inputPayload}
            </p>
          )}
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold tracking-wider text-zinc-400 uppercase">Steps</h3>
          <button
            type="button"
            onClick={addStep}
            disabled={disabled}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/[0.08] hover:text-white disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Add step</span>
          </button>
        </div>

        {draft.steps.length === 0 && (
          <p className="rounded-lg border border-dashed border-white/[0.08] p-4 text-center text-xs text-zinc-500">
            No steps yet. A workflow with zero steps is technically permitted, but nothing will
            execute.
          </p>
        )}

        {draft.steps.map((step, index) => {
          const agent = agentByType.get(step.agentType);
          const stepError = errors.steps[step.key];
          return (
            <div
              key={step.key}
              className="space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-zinc-400">Step {index + 1}</span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => moveStep(index, -1)}
                    disabled={disabled || index === 0}
                    aria-label={`Move step ${index + 1} up`}
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-400 hover:bg-white/[0.06] hover:text-white disabled:opacity-30"
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => moveStep(index, 1)}
                    disabled={disabled || index === draft.steps.length - 1}
                    aria-label={`Move step ${index + 1} down`}
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-400 hover:bg-white/[0.06] hover:text-white disabled:opacity-30"
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => removeStep(step.key)}
                    disabled={disabled}
                    aria-label={`Remove step ${index + 1}`}
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-rose-400 hover:bg-rose-950/40 disabled:opacity-30"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <label
                    htmlFor={`step-name-${step.key}`}
                    className="block text-[11px] font-medium text-zinc-500"
                  >
                    Step name
                  </label>
                  <input
                    id={`step-name-${step.key}`}
                    type="text"
                    value={step.name}
                    onChange={(e) => updateStep(step.key, { name: e.target.value })}
                    disabled={disabled}
                    className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-white focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
                    placeholder="e.g. generate-api"
                  />
                </div>

                <div className="space-y-1">
                  <label
                    htmlFor={`step-agent-${step.key}`}
                    className="block text-[11px] font-medium text-zinc-500"
                  >
                    Agent
                  </label>
                  <select
                    id={`step-agent-${step.key}`}
                    value={step.agentType}
                    onChange={(e) => updateStep(step.key, { agentType: e.target.value })}
                    disabled={disabled}
                    className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-white focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
                  >
                    <option value="" className="bg-[#0B1120]">
                      Select an agent…
                    </option>
                    {agents.map((candidate) => (
                      <option
                        key={candidate.agent_type}
                        value={candidate.agent_type}
                        className="bg-[#0B1120]"
                      >
                        {candidate.agent_type} — {agentBadge(candidate)}
                      </option>
                    ))}
                  </select>
                  {step.agentType && agent && !agent.registered && (
                    <p className="text-[11px] text-amber-400">
                      Warning: this agent is not currently registered in the running backend —
                      execution will fail until it is.
                    </p>
                  )}
                </div>

                <div className="space-y-1">
                  <label
                    htmlFor={`step-max-attempts-${step.key}`}
                    className="block text-[11px] font-medium text-zinc-500"
                  >
                    Max attempts
                  </label>
                  <input
                    id={`step-max-attempts-${step.key}`}
                    type="number"
                    min={1}
                    value={step.maxAttempts}
                    onChange={(e) =>
                      updateStep(step.key, { maxAttempts: Number(e.target.value) || 1 })
                    }
                    disabled={disabled}
                    className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-white focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
                  />
                </div>

                <div className="space-y-1">
                  <label
                    htmlFor={`step-compensation-${step.key}`}
                    className="block text-[11px] font-medium text-zinc-500"
                  >
                    Compensation handler (optional)
                  </label>
                  <select
                    id={`step-compensation-${step.key}`}
                    value={step.compensationHandler}
                    onChange={(e) => updateStep(step.key, { compensationHandler: e.target.value })}
                    disabled={disabled}
                    className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-white focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
                  >
                    <option value="" className="bg-[#0B1120]">
                      None
                    </option>
                    {demoRegistered && (
                      <option value="demo.undo" className="bg-[#0B1120]">
                        demo.undo
                      </option>
                    )}
                  </select>
                  {!demoRegistered && (
                    <p className="text-[11px] text-zinc-500">
                      Only <code>demo.undo</code> is supported in this prototype, and only while
                      demo mode is registered.
                    </p>
                  )}
                </div>
              </div>

              <div className="space-y-1">
                <label
                  htmlFor={`step-input-${step.key}`}
                  className="block text-[11px] font-medium text-zinc-500"
                >
                  Step input (JSON)
                </label>
                <textarea
                  id={`step-input-${step.key}`}
                  value={step.inputPayloadText}
                  onChange={(e) => updateStep(step.key, { inputPayloadText: e.target.value })}
                  disabled={disabled}
                  rows={2}
                  className="w-full resize-none rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 font-mono text-xs text-white focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
                  placeholder="{}"
                />
              </div>

              {stepError && (
                <p className="text-xs text-rose-400" role="alert">
                  {stepError}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
