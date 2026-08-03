'use client';

import * as React from 'react';
import { Info, Sparkles } from 'lucide-react';
import { AppLayout, PromptCard } from '@/components/common';
import { InlineError, describeError } from '@/components/common/inline-error';
import {
  WorkflowBuilder,
  ExecutionPanel,
  type WorkflowDraft,
  createEmptyDraft,
  createEmptyStep,
  validateDraft,
  draftHasErrors,
  draftToWorkflowCreate,
} from '@/components/workflow';
import { WORKFLOW_TEMPLATES } from '@/lib/templates';
import { createWorkflow, executeWorkflow, compensateWorkflow } from '@/services/workflows';
import type { WorkflowRead } from '@/types/backend';

type Mode = 'templates' | 'builder' | 'created';

export default function ChatPage() {
  const [mode, setMode] = React.useState<Mode>('templates');
  const [goalText, setGoalText] = React.useState('');
  const [draft, setDraft] = React.useState<WorkflowDraft>(createEmptyDraft());
  const [creating, setCreating] = React.useState(false);
  const [createError, setCreateError] = React.useState<string | null>(null);
  const [workflow, setWorkflow] = React.useState<WorkflowRead | null>(null);
  const [executing, setExecuting] = React.useState(false);
  const [compensating, setCompensating] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const startFromGoal = () => {
    if (!goalText.trim()) return;
    setDraft({
      ...createEmptyDraft(),
      name: goalText.trim().slice(0, 120),
      description: goalText.trim(),
    });
    setMode('builder');
  };

  const startFromTemplate = (templateId: string) => {
    const template = WORKFLOW_TEMPLATES.find((t) => t.id === templateId);
    if (!template) return;
    setDraft({
      name: template.workflowName,
      description: template.workflowDescription,
      inputPayloadText: template.inputPayloadText,
      steps: template.steps.map((step) => ({
        ...createEmptyStep(),
        name: step.name,
        agentType: step.agentType,
        maxAttempts: step.maxAttempts,
      })),
    });
    setMode('builder');
  };

  const [errors, setErrors] = React.useState(() => validateDraft(draft));

  const handleDraftChange = (next: WorkflowDraft) => {
    setDraft(next);
    setErrors(validateDraft(next));
  };

  const handleCreate = async () => {
    const currentErrors = validateDraft(draft);
    setErrors(currentErrors);
    if (draftHasErrors(currentErrors)) return;

    setCreating(true);
    setCreateError(null);
    try {
      const created = await createWorkflow(draftToWorkflowCreate(draft));
      setWorkflow(created);
      setMode('created');
    } catch (error) {
      setCreateError(describeError(error).body);
    } finally {
      setCreating(false);
    }
  };

  const handleExecute = async () => {
    if (!workflow) return;
    setExecuting(true);
    setActionError(null);
    try {
      const updated = await executeWorkflow(workflow.id);
      setWorkflow(updated);
    } catch (error) {
      setActionError(describeError(error).body);
    } finally {
      setExecuting(false);
    }
  };

  const handleCompensate = async () => {
    if (!workflow) return;
    setCompensating(true);
    setActionError(null);
    try {
      const updated = await compensateWorkflow(workflow.id);
      setWorkflow(updated);
    } catch (error) {
      setActionError(describeError(error).body);
    } finally {
      setCompensating(false);
    }
  };

  const startOver = () => {
    setMode('templates');
    setGoalText('');
    setDraft(createEmptyDraft());
    setWorkflow(null);
    setCreateError(null);
    setActionError(null);
  };

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col overflow-y-auto p-6 md:p-8">
        <div className="space-y-2">
          <span className="text-xs font-bold tracking-wider text-blue-400 uppercase">
            New Workflow
          </span>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Create and review the workflow steps, assign agents, then execute through Keystone.
          </h1>
          <p className="flex items-start gap-2 rounded-lg border border-blue-900/30 bg-blue-950/20 p-3 text-xs text-blue-300">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Keystone does not automatically decompose your goal or select agents for you in
              this prototype. You define each step and choose its agent manually. Automatic
              planning and agent routing are <strong>coming in Phase 6</strong>.
            </span>
          </p>
        </div>

        {mode === 'templates' && (
          <div className="mt-8 space-y-8">
            <div className="space-y-3">
              <label htmlFor="goal-input" className="block text-xs font-medium text-zinc-400">
                Describe your goal (optional starting point)
              </label>
              <textarea
                id="goal-input"
                value={goalText}
                onChange={(e) => setGoalText(e.target.value)}
                rows={3}
                placeholder="e.g. Build a REST API with FastAPI and validate the output"
                className="w-full resize-none rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 text-sm text-white placeholder:text-zinc-500 focus:border-blue-500/50 focus:outline-none"
              />
              <button
                type="button"
                onClick={startFromGoal}
                disabled={!goalText.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Sparkles className="h-3.5 w-3.5" />
                <span>Start workflow draft</span>
              </button>
            </div>

            <div className="space-y-3">
              <h2 className="text-xs font-bold tracking-wider text-zinc-400 uppercase">
                Or start from a template
              </h2>
              <p className="text-[11px] text-zinc-500">
                Static, locally-defined starting points — not generated, learned, or personalized.
                Review and edit every field before creating the workflow.
              </p>
              <div className="grid w-full gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {WORKFLOW_TEMPLATES.map((template) => (
                  <PromptCard
                    key={template.id}
                    title={template.title}
                    subtitle={template.description}
                    prompt={template.id}
                    icon={Sparkles}
                    iconBg="bg-blue-600/20 text-blue-400"
                    onSelect={startFromTemplate}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {mode === 'builder' && (
          <div className="mt-8 max-w-3xl space-y-4">
            <WorkflowBuilder draft={draft} onChange={handleDraftChange} errors={errors} disabled={creating} />
            {createError && <InlineError message={createError} />}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setMode('templates')}
                disabled={creating}
                className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-xs text-zinc-300 hover:bg-white/[0.08] disabled:opacity-50"
              >
                Back
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating || draftHasErrors(errors)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {creating ? 'Creating…' : 'Create Workflow'}
              </button>
            </div>
          </div>
        )}

        {mode === 'created' && workflow && (
          <div className="mt-8 max-w-2xl space-y-4">
            {actionError && <InlineError message={actionError} />}
            <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
              <ExecutionPanel
                workflow={workflow}
                onExecute={handleExecute}
                onCompensate={handleCompensate}
                executing={executing}
                compensating={compensating}
              />
            </div>
            <button
              type="button"
              onClick={startOver}
              className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-xs text-zinc-300 hover:bg-white/[0.08]"
            >
              Start another workflow
            </button>
          </div>
        )}
      </main>
    </AppLayout>
  );
}
