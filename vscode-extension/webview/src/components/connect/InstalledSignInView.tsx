import React, { useEffect, useState } from 'react';
import { ArrowLeft, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import {
  activateRuntime,
  createAgentConnection,
  createConnectedAgent,
  fetchAgentConnections,
  fetchDetectedRuntimes,
} from '../../api/keystoneClient';
import type { AgentConnection, ConnectedAgentSummary, DetectedRuntime } from '../../types/keystone';

export interface CategoryDetailViewProps {
  onBack: () => void;
}

export interface InstalledSignInViewProps extends CategoryDetailViewProps {
  onAgentsChanged: () => void;
  existingAgents: ConnectedAgentSummary[];
}

type Step =
  | { kind: 'list' }
  | { kind: 'activating'; runtime: DetectedRuntime }
  | { kind: 'naming'; runtime: DetectedRuntime; connection: AgentConnection }
  | { kind: 'done'; agentId: string };

function suggestAgentId(runtimeType: string, taken: Set<string>): string {
  const base = `${runtimeType.replace(/_/g, '-')}-work`;
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}-${n}`)) n += 1;
  return `${base}-${n}`;
}

/**
 * Installed/subscription runtime connector -- the one Connect Agent
 * category backed by a real, end-to-end connector (Stage 8C.3): discovery
 * (`GET /api/v1/agents`), deliberate activation (`POST /runtime-
 * connections/{id}/activate`), connection creation, and Keystone agent
 * identity creation, all against the real backend. Never fabricates
 * availability -- a runtime not found on PATH always reads "Not detected,"
 * never a fake "Connect" affordance.
 */
export const InstalledSignInView: React.FC<InstalledSignInViewProps> = ({
  onBack,
  onAgentsChanged,
  existingAgents,
}) => {
  const [runtimes, setRuntimes] = useState<DetectedRuntime[] | null>(null);
  const [connections, setConnections] = useState<AgentConnection[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>({ kind: 'list' });
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchDetectedRuntimes(), fetchAgentConnections()])
      .then(([detected, conns]) => {
        if (cancelled) return;
        setRuntimes(detected);
        setConnections(conns);
      })
      .catch(() => {
        if (cancelled) return;
        setLoadError('Unable to reach the Keystone backend.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleConnect = async (runtime: DetectedRuntime) => {
    setActionError(null);
    setBusy(true);
    setStep({ kind: 'activating', runtime });
    try {
      const activation = await activateRuntime(runtime.agent_type);
      if (activation.installation_status !== 'installed') {
        setActionError(`${runtime.display_name} is not installed on this machine.`);
        setStep({ kind: 'list' });
        return;
      }

      const connectionId = `${runtime.agent_type}-local`;
      let connection = connections.find((c) => c.connection_id === connectionId) ?? null;
      if (connection === null) {
        try {
          connection = await createAgentConnection({
            connection_id: connectionId,
            display_name: `${runtime.display_name} (local)`,
            connection_kind: 'installed_runtime',
            provider_or_runtime: runtime.agent_type,
          });
          setConnections((prev) => [...prev, connection as AgentConnection]);
        } catch {
          // Idempotent: another connect attempt may have just created the
          // same connection_id first. Re-fetch rather than treat this as
          // a hard failure -- Stage 8C.3 requires "duplicate connection
          // != fatal backend-unavailable state."
          const refreshed = await fetchAgentConnections();
          setConnections(refreshed);
          connection = refreshed.find((c) => c.connection_id === connectionId) ?? null;
          if (connection === null) {
            throw new Error('Unable to create or reuse the connection for this runtime.');
          }
        }
      }

      setStep({ kind: 'naming', runtime, connection });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to connect this runtime.');
      setStep({ kind: 'list' });
    } finally {
      setBusy(false);
    }
  };

  if (step.kind === 'naming') {
    return (
      <NameAgentForm
        runtime={step.runtime}
        connection={step.connection}
        existingAgents={existingAgents}
        onBack={() => setStep({ kind: 'list' })}
        onCreated={(agentId) => {
          onAgentsChanged();
          setStep({ kind: 'done', agentId });
        }}
      />
    );
  }

  if (step.kind === 'done') {
    return (
      <div className="connect-agent-view">
        <h2 className="connect-agent-heading">Installed / Sign in</h2>
        <div className="connect-category-detail connect-success">
          <CheckCircle2 size={28} className="connect-success-icon" />
          <p>
            <strong>{step.agentId}</strong> is connected and ready to use.
          </p>
          <div className="connect-form-actions">
            <button type="button" className="btn-connect-agent" onClick={() => setStep({ kind: 'list' })}>
              Connect another agent
            </button>
            <button type="button" className="btn-link" onClick={onBack}>
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onBack}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">Installed / Sign in</h2>
      {loadError && (
        <p className="connect-error-text" role="alert">
          {loadError}
        </p>
      )}
      {actionError && (
        <p className="connect-error-text" role="alert">
          {actionError}
        </p>
      )}
      {runtimes === null && !loadError && (
        <p className="connect-loading-text">
          <Loader2 size={14} className="spin" /> Checking installed runtimes...
        </p>
      )}
      {runtimes !== null && (
        <ul className="runtime-list" aria-label="Installed runtimes">
          {runtimes.map((runtime) => (
            <RuntimeRow
              key={runtime.agent_type}
              runtime={runtime}
              busy={busy && step.kind === 'activating' && step.runtime.agent_type === runtime.agent_type}
              disabled={busy}
              onConnect={() => void handleConnect(runtime)}
            />
          ))}
        </ul>
      )}
    </div>
  );
};

const RuntimeRow: React.FC<{
  runtime: DetectedRuntime;
  busy: boolean;
  disabled: boolean;
  onConnect: () => void;
}> = ({ runtime, busy, disabled, onConnect }) => {
  const installed = runtime.installation_status === 'installed';

  return (
    <li className="runtime-row">
      <div className="runtime-row-info">
        <span className="runtime-row-name">{runtime.display_name}</span>
        {installed ? (
          <span className="runtime-row-status runtime-row-status-ok">
            <CheckCircle2 size={12} /> Installed
            {runtime.authentication_status === 'authenticated' && ' · Authenticated'}
          </span>
        ) : (
          <span className="runtime-row-status runtime-row-status-missing">
            <XCircle size={12} /> Not detected
          </span>
        )}
      </div>
      {installed ? (
        <button type="button" className="btn-connect-runtime" disabled={disabled} onClick={onConnect}>
          {busy ? <Loader2 size={13} className="spin" /> : 'Connect'}
        </button>
      ) : null}
    </li>
  );
};

const NameAgentForm: React.FC<{
  runtime: DetectedRuntime;
  connection: AgentConnection;
  existingAgents: ConnectedAgentSummary[];
  onBack: () => void;
  onCreated: (agentId: string) => void;
}> = ({ runtime, connection, existingAgents, onBack, onCreated }) => {
  const taken = new Set(existingAgents.map((a) => a.agent_id));
  const [agentId, setAgentId] = useState(() => suggestAgentId(runtime.agent_type, taken));
  const [displayName, setDisplayName] = useState(() => `${runtime.display_name} agent`);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const cleanId = agentId.trim();
    if (!cleanId) {
      setError('Agent ID is required.');
      return;
    }
    if (taken.has(cleanId)) {
      setError(`An agent named '${cleanId}' already exists.`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createConnectedAgent({
        agent_id: cleanId,
        display_name: displayName.trim() || cleanId,
        connection_id: connection.connection_id,
        capabilities: runtime.capabilities,
      });
      onCreated(cleanId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create this agent.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onBack} disabled={submitting}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">Name this agent</h2>
      <p className="connect-form-hint">
        Connected via <strong>{connection.display_name}</strong>. You can create more than one agent on
        this connection.
      </p>
      <form className="connect-agent-form" onSubmit={(e) => void handleSubmit(e)}>
        <label className="connect-form-field">
          <span>Agent name</span>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            disabled={submitting}
          />
        </label>
        <label className="connect-form-field">
          <span>Agent ID</span>
          <input
            type="text"
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            disabled={submitting}
            required
          />
        </label>
        <div className="connect-capability-list" aria-label="Capabilities">
          {runtime.capabilities.map((cap) => (
            <span key={cap} className="connect-capability-badge">
              {cap.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
        {error && (
          <p className="connect-error-text" role="alert">
            {error}
          </p>
        )}
        <div className="connect-form-actions">
          <button type="submit" className="btn-connect-agent" disabled={submitting}>
            {submitting ? <Loader2 size={13} className="spin" /> : 'Create agent'}
          </button>
        </div>
      </form>
    </div>
  );
};
