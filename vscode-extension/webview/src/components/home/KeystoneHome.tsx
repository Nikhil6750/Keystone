import React, { useCallback, useState } from 'react';
import { KeystoneHeader } from './KeystoneHeader';
import { WelcomeState } from './WelcomeState';
import { PromptComposer } from '../composer/PromptComposer';
import { ConnectAgentView } from '../connect/ConnectAgentView';
import { ExecutionProgress } from '../execution/ExecutionProgress';
import { ExecutionResult } from '../execution/ExecutionResult';
import { BackendUnavailable } from '../backend/BackendUnavailable';
import { useConnectedAgents } from '../../hooks/useConnectedAgents';
import { useOrchestration } from '../../hooks/useOrchestration';

/**
 * Top-level prompt-first Keystone experience (Stage 8C.3 UI redesign).
 * Replaces the previous tabbed Workflow Builder / Agent Manager /
 * Knowledge / Workspace scaffold as the default view. Those concepts are
 * not deleted -- they simply no longer appear in the primary path.
 */
export const KeystoneHome: React.FC = () => {
  const { agents, availability, refetch } = useConnectedAgents();
  const { phase, events, result, submitError, submit, reset } = useOrchestration();
  const [screen, setScreen] = useState<'home' | 'connect'>('home');

  const connectedAgentIds = agents.map((agent) => agent.agent_id);

  const handleSubmit = useCallback(
    (goal: string) => {
      submit(goal, connectedAgentIds);
    },
    [submit, connectedAgentIds]
  );

  const handleStartOver = useCallback(() => {
    reset();
  }, [reset]);

  if (availability === 'unavailable') {
    return (
      <div className="keystone-home">
        <KeystoneHeader connectedAgentCount={0} onOpenAgentSettings={() => setScreen('connect')} />
        <div className="keystone-body">
          <BackendUnavailable onRetry={refetch} />
        </div>
      </div>
    );
  }

  if (screen === 'connect') {
    return (
      <div className="keystone-home">
        <KeystoneHeader
          connectedAgentCount={agents.length}
          onOpenAgentSettings={() => setScreen('connect')}
        />
        <div className="keystone-body">
          <ConnectAgentView
            onClose={() => {
              setScreen('home');
              refetch();
            }}
          />
        </div>
      </div>
    );
  }

  const isBusy = phase === 'submitting' || phase === 'running';

  return (
    <div className="keystone-home">
      <KeystoneHeader
        connectedAgentCount={agents.length}
        onOpenAgentSettings={() => setScreen('connect')}
      />
      <div className="keystone-body">
        {phase === 'idle' && (
          <WelcomeState
            hasConnectedAgents={agents.length > 0}
            onConnectAgent={() => setScreen('connect')}
          />
        )}
        {isBusy && <ExecutionProgress events={events} />}
        {(phase === 'completed' || phase === 'failed') && (
          <ExecutionResult result={result} onStartOver={handleStartOver} />
        )}
        {submitError && phase === 'idle' && (
          <p className="result-summary" role="alert">
            {submitError}
          </p>
        )}
      </div>
      <PromptComposer
        disabled={isBusy || availability === 'checking'}
        onSubmit={handleSubmit}
      />
    </div>
  );
};
