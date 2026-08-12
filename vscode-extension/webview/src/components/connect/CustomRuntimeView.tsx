import React, { useState } from 'react';
import { ArrowLeft, CheckCircle2, Loader2, ShieldAlert } from 'lucide-react';
import { createAgentConnection, createConnectedAgent } from '../../api/keystoneClient';
import type { CategoryDetailViewProps } from './InstalledSignInView';

export interface CustomRuntimeViewProps extends CategoryDetailViewProps {
  onAgentsChanged: () => void;
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/**
 * Custom/company runtime connections (an internal engine, a custom
 * compatible endpoint) -- identified only by an open string ID, never a
 * built-in vendor list.
 *
 * This is metadata registration only: a name and an optional descriptive
 * endpoint string, stored as connection metadata. It deliberately has no
 * field that could become a shell command -- there is no generic
 * "run this on the machine" concept anywhere in this form, and none of
 * this component's own code ever constructs or executes one. See
 * `app.engine.connections.models.validate_metadata` for the backend's own
 * independent rejection of any secret-shaped key here too.
 */
export const CustomRuntimeView: React.FC<CustomRuntimeViewProps> = ({ onBack, onAgentsChanged }) => {
  const [runtimeName, setRuntimeName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const runtimeClean = runtimeName.trim();
    if (!runtimeClean) {
      setError('Runtime name is required.');
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const connectionId = `custom-${slugify(runtimeClean)}`;
      const connection = await createAgentConnection({
        connection_id: connectionId,
        display_name: runtimeClean,
        connection_kind: 'custom',
        provider_or_runtime: runtimeClean,
        metadata: description.trim() ? { description: description.trim() } : undefined,
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
        <h2 className="connect-agent-heading">Custom</h2>
        <div className="connect-category-detail connect-success">
          <CheckCircle2 size={28} className="connect-success-icon" />
          <p>
            <strong>{done}</strong> was created.
          </p>
          <p className="connect-form-hint">
            <ShieldAlert size={13} /> Execution adapter not yet available for custom connections -- this
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
      <h2 className="connect-agent-heading">Custom</h2>
      <form className="connect-agent-form" onSubmit={(e) => void handleSubmit(e)}>
        <label className="connect-form-field">
          <span>Runtime name</span>
          <input
            type="text"
            value={runtimeName}
            onChange={(e) => setRuntimeName(e.target.value)}
            placeholder="e.g. acme-internal-agent"
            disabled={submitting}
            required
          />
        </label>
        <label className="connect-form-field">
          <span>Description (optional)</span>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. internal review bot, v2 endpoint"
            disabled={submitting}
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
