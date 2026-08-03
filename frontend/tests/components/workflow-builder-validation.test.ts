import { describe, expect, it } from 'vitest';
import {
  createEmptyDraft,
  createEmptyStep,
  draftHasErrors,
  draftToWorkflowCreate,
  validateDraft,
} from '@/components/workflow/workflow-builder';

describe('draftToWorkflowCreate', () => {
  it('excludes internal/server-assigned fields from the submitted payload', () => {
    const draft = createEmptyDraft();
    draft.name = 'My workflow';
    draft.steps = [{ ...createEmptyStep(), name: 'step-a', agentType: 'demo' }];

    const payload = draftToWorkflowCreate(draft);
    const steps = payload.steps ?? [];

    expect(payload).not.toHaveProperty('id');
    expect(payload).not.toHaveProperty('status');
    expect(payload).not.toHaveProperty('version');
    expect(payload).not.toHaveProperty('created_at');
    expect(steps[0]).not.toHaveProperty('id');
    expect(steps[0]).not.toHaveProperty('status');
    expect(steps[0]).not.toHaveProperty('attempt_count');
    expect(steps[0]).toMatchObject({ name: 'step-a', agent_type: 'demo', position: 0 });
  });
});

describe('validateDraft', () => {
  it('rejects a blank workflow name', () => {
    const draft = createEmptyDraft();
    draft.name = '   ';

    const errors = validateDraft(draft);

    expect(errors.name).toBeTruthy();
    expect(draftHasErrors(errors)).toBe(true);
  });

  it('rejects a blank step name', () => {
    const draft = createEmptyDraft();
    draft.name = 'Valid name';
    draft.steps = [{ ...createEmptyStep(), name: '', agentType: 'demo' }];

    const errors = validateDraft(draft);

    expect(errors.steps[draft.steps[0].key]).toBeTruthy();
  });

  it('rejects max_attempts below 1', () => {
    const draft = createEmptyDraft();
    draft.name = 'Valid name';
    draft.steps = [{ ...createEmptyStep(), name: 'step', agentType: 'demo', maxAttempts: 0 }];

    const errors = validateDraft(draft);

    expect(errors.steps[draft.steps[0].key]).toMatch(/at least 1/);
  });

  it('rejects invalid JSON in a step input payload', () => {
    const draft = createEmptyDraft();
    draft.name = 'Valid name';
    draft.steps = [
      { ...createEmptyStep(), name: 'step', agentType: 'demo', inputPayloadText: '{not valid' },
    ];

    const errors = validateDraft(draft);

    expect(errors.steps[draft.steps[0].key]).toMatch(/Invalid JSON/);
  });

  it('accepts a fully valid draft with no errors', () => {
    const draft = createEmptyDraft();
    draft.name = 'Valid workflow';
    draft.steps = [{ ...createEmptyStep(), name: 'step', agentType: 'demo' }];

    const errors = validateDraft(draft);

    expect(draftHasErrors(errors)).toBe(false);
  });
});
