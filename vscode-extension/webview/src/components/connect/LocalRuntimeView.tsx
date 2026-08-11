import React, { useState } from 'react';
import { ArrowLeft, CheckCircle2, Loader2, ShieldAlert } from 'lucide-react';
import { createAgentConnection, createConnectedAgent } from '../../api/keystoneClient';
import type { CategoryDetailViewProps } from './InstalledSignInView';

export interface LocalRuntimeViewProps extends CategoryDetailViewProps {
  onAgentsChanged: () => void;
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Loopback-only: `127.0.0.1`, `[::1]`, or `localhost`, `http`/`https` only.
 * No generic backend fetch exists for this connection kind yet, so this is
 * a forward-looking guard, not a live SSRF mitigation -- but the same rule
 * a future local executor would need to enforce server-side too. */
const LOOPBACK_ENDPOINT_PATTERN = /^https?:\/\/(127\.0\.0\.1|\[::1\]|localhost)(:\d{1,5})?(\/.*)?$/i;

/**
 * Local runtime/model connector (e.g. an Ollama server, a local
 * OpenAI-compatible endpoint). `provider_or_runtime` stays an open string.
 * No generic local executor exists in this backend yet -- a connection and
 * agent created here are real but not yet executable, same honesty rule as
 * `ApiByokView`.
 */
export const LocalRuntimeView: React.FC<LocalRuntimeViewProps> = ({ onBack, onAgentsChanged }) => {
  const [runtime, setRuntime] = useState('');
  const [endpoint, setEndpoint] = useState('http://127.0.0.1:11434');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const runtimeClean = runtime.trim();
    const endpointClean = endpoint.trim();
    if (!runtimeClean) {
      setError('Runtime name is required.');
      return;
    }
    if (!LOOPBACK_ENDPOINT_PATTERN.test(endpointClean)) {
      setError('Endpoint must be a loopback address (http://127.0.0.1:<port> or http://localhost:<port>).');
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const connectionId = `local-${slugify(runtimeClean)}`;
      const connection = await createAgentConnection({
        connection_id: connectionId,
        display_name: runtimeClean,
        connection_kind: 'local',
        provider_or_runtime: runtimeClean,
        metadata: { endpoint: endpointClean },
      }).catch(async () => ({ connection_id: connectionId }) as { connection_id: string });

      const agentId = `${slugify(runtimeClean)}-agent`;
      await createConnectedAgent({
        agent_id: agentId,
        display_name: runtimeClean,
        connection_id: connection.connection_id,
        capabilities: [],
      });

      onAgentsChanged();
      setDone(agentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create this connection.');
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="connect-agent-view">
        <h2 className="connect-agent-heading">Local</h2>
        <div className="connect-category-detail connect-success">
          <CheckCircle2 size={28} className="connect-success-icon" />
          <p>
            <strong>{done}</strong> was created.
          </p>
          <p className="connect-form-hint">
            <ShieldAlert size={13} /> Execution adapter not yet available for local connections -- this
            agent will not be selected for a task yet.
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

  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onBack} disabled={submitting}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">Local</h2>
      <form className="connect-agent-form" onSubmit={(e) => void handleSubmit(e)}>
        <label className="connect-form-field">
          <span>Runtime name</span>
          <input
            type="text"
            value={runtime}
            onChange={(e) => setRuntime(e.target.value)}
            placeholder="e.g. ollama"
            disabled={submitting}
            required
          />
        </label>
        <label className="connect-form-field">
          <span>Endpoint (loopback only)</span>
          <input
            type="text"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            disabled={submitting}
            required
          />
        </label>
        {error && (
          <p className="connect-error-text" role="alert">
            {error}
          </p>
        )}
        <div className="connect-form-actions">
          <button type="submit" className="btn-connect-agent" disabled={submitting}>
            {submitting ? <Loader2 size={13} className="spin" /> : 'Connect'}
          </button>
        </div>
      </form>
    </div>
  );
};
