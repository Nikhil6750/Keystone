import React, { useEffect, useState } from 'react';
import { ArrowLeft, CheckCircle2, XCircle, Loader2, ChevronDown } from 'lucide-react';
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
  | { kind: 'connecting'; runtime: DetectedRuntime }
  | { kind: 'done'; runtime: DetectedRuntime; agentId: string };

/**
 * Runtime identities Keystone never surfaces as a normal "connect this"
 * option: a demo/simulation adapter is developer-only, not a real agent a
 * user came here to connect. Backend-driven exclusion by design (no static
 * per-vendor branch) -- this is the one, deliberately narrow exception.
 */
const HIDDEN_RUNTIME_TYPES = new Set(['demo']);

function suggestAgentId(runtimeType: string, taken: Set<string>): string {
  const base = runtimeType.replace(/_/g, '-');
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
 *
 * One click, no naming screen: `connection_id`/`agent_id`/`display_name`
 * are all derived deterministically from the runtime's own id
 * (`suggestAgentId`) -- Connection and Agent still exist as separate
 * backend entities (Connection != Agent), just never surfaced to the user
 * during this normal flow. Power users who want a custom name/second
 * identity on the same connection belong behind a future Advanced ->
 * Agent profiles surface, not here.
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

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchDetectedRuntimes(), fetchAgentConnections()])
      .then(([detected, conns]) => {
        if (cancelled) return;
        setRuntimes(detected.filter((r) => !HIDDEN_RUNTIME_TYPES.has(r.agent_type)));
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
    setStep({ kind: 'connecting', runtime });
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

      const taken = new Set(existingAgents.map((a) => a.agent_id));
      let agentId = suggestAgentId(runtime.agent_type, taken);
      try {
        await createConnectedAgent({
          agent_id: agentId,
          display_name: runtime.display_name,
          connection_id: connection.connection_id,
          capabilities: runtime.capabilities,
        });
      } catch {
        // Extremely unlikely (another connect attempt racing the same
        // suggested id) -- retry once with the next deterministic suffix
        // rather than surface a raw "already exists" error for a screen
        // the user never typed an id into.
        agentId = suggestAgentId(runtime.agent_type, new Set([...taken, agentId]));
        await createConnectedAgent({
          agent_id: agentId,
          display_name: runtime.display_name,
          connection_id: connection.connection_id,
          capabilities: runtime.capabilities,
        });
      }

      onAgentsChanged();
      setStep({ kind: 'done', runtime, agentId });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to connect this runtime.');
      setStep({ kind: 'list' });
    }
  };

  if (step.kind === 'done') {
    return (
      <div className="connect-agent-view">
        <h2 className="connect-agent-heading">Installed / Sign in</h2>
        <div className="connect-category-detail connect-success">
          <CheckCircle2 size={28} className="connect-success-icon" />
          <p>
            <strong>{step.runtime.display_name}</strong> connected.
          </p>
          <div className="connect-form-actions">
            <button type="button" className="btn-link" onClick={onBack}>
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  const busy = step.kind === 'connecting';
  const detected = (runtimes ?? []).filter((r) => r.installation_status === 'installed');
  const other = (runtimes ?? []).filter((r) => r.installation_status !== 'installed');

  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onBack} disabled={busy}>
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
      {runtimes !== null && detected.length > 0 && (
        <>
          <p className="agent-management-heading">Detected on this machine</p>
          <ul className="runtime-list" aria-label="Installed runtimes">
            {detected.map((runtime) => (
              <RuntimeRow
                key={runtime.agent_type}
                runtime={runtime}
                busy={busy && step.kind === 'connecting' && step.runtime.agent_type === runtime.agent_type}
                disabled={busy}
                onConnect={() => void handleConnect(runtime)}
              />
            ))}
          </ul>
        </>
      )}
      {runtimes !== null && detected.length === 0 && !loadError && (
        <p className="connect-form-hint">No supported runtime was detected on this machine.</p>
      )}
      {other.length > 0 && (
        <details className="runtime-other-details">
          <summary className="runtime-other-summary">
            <ChevronDown size={13} /> Other supported connectors ({other.length})
          </summary>
          <ul className="runtime-list" aria-label="Other supported connectors">
            {other.map((runtime) => (
              <RuntimeRow key={runtime.agent_type} runtime={runtime} busy={false} disabled onConnect={() => {}} />
            ))}
          </ul>
        </details>
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
            <CheckCircle2 size={12} />
            {runtime.authentication_status === 'authenticated' ? 'Installed · Signed in' : 'Installed'}
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
