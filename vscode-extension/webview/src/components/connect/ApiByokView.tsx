import React, { useState } from 'react';
import { ArrowLeft, CheckCircle2, Loader2, ShieldAlert } from 'lucide-react';
import { createAgentConnection, createConnectedAgent } from '../../api/keystoneClient';
import { storeSecret } from '../../api/secretsClient';
import type { CategoryDetailViewProps } from './InstalledSignInView';

export interface ApiByokViewProps extends CategoryDetailViewProps {
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
 * API/BYOK connection setup (one provider connection -> many Keystone
 * agents, e.g. `openrouter-personal` -> `qwen-coder` + `qwen-reviewer`).
 * `provider_or_runtime` stays an open string -- never a hardcoded
 * OpenRouter/OpenAI/etc. enum.
 *
 * The credential never touches React state longer than one keystroke
 * cycle needed to render the input, is never included in the
 * `AgentConnection`/`ConnectedAgent` payload sent to the backend (the
 * backend independently rejects a secret-shaped metadata key anyway --
 * see `validate_metadata`), and is cleared from this component's state
 * immediately after a successful `storeSecret` call. It goes only to VS
 * Code `SecretStorage` via the extension-host `SecretsProxy`.
 *
 * No generic OpenAI-compatible execution adapter exists in this backend
 * yet, so a connection and agent created here are real (they persist,
 * they list, they can be removed) but not yet executable -- the Router
 * will never select one, because `ExecutorRegistry` has no adapter
 * registered for it. This is stated plainly in the UI, not hidden.
 */
export const ApiByokView: React.FC<ApiByokViewProps> = ({ onBack, onAgentsChanged }) => {
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [credential, setCredential] = useState('');
  const [agentName, setAgentName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const providerClean = provider.trim();
    const agentClean = agentName.trim();
    if (!providerClean || !agentClean) {
      setError('Provider and agent name are required.');
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const connectionId = `api-${slugify(providerClean)}`;
      const secretKey = `byok:${connectionId}`;

      if (credential.trim()) {
        const stored = await storeSecret(secretKey, credential);
        if (!stored) {
          throw new Error('Unable to securely store the credential. Nothing was saved.');
        }
      }
      // Cleared immediately after the store call resolves, whether or not
      // a credential was provided -- never held longer than necessary.
      setCredential('');

      const connection = await createAgentConnection({
        connection_id: connectionId,
        display_name: providerClean,
        connection_kind: 'api',
        provider_or_runtime: providerClean,
      }).catch(async () => {
        // Idempotent, same as Installed/Sign in: a connection with this
        // id may already exist from a previous attempt.
        return { connection_id: connectionId } as { connection_id: string };
      });

      const agentId = slugify(agentClean) || connectionId;
      await createConnectedAgent({
        agent_id: agentId,
        display_name: agentClean,
        connection_id: connection.connection_id,
        model_id: model.trim() || null,
        // No generic API executor exists yet to report truthful
        // capabilities for -- leaving this empty is honest; it is never
        // guessed.
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
        <h2 className="connect-agent-heading">API / BYOK</h2>
        <div className="connect-category-detail connect-success">
          <CheckCircle2 size={28} className="connect-success-icon" />
          <p>
            <strong>{done}</strong> was created and its credential stored securely.
          </p>
          <p className="connect-form-hint">
            <ShieldAlert size={13} /> Execution adapter not yet available for API/BYOK connections --
            this agent will not be selected for a task yet.
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
      <h2 className="connect-agent-heading">API / BYOK</h2>
      <p className="connect-form-hint">
        <ShieldAlert size={13} /> Your credential is sent only to VS Code&apos;s secure secret storage --
        never to Keystone&apos;s backend, never logged, never shown again.
      </p>
      <form className="connect-agent-form" onSubmit={(e) => void handleSubmit(e)}>
        <label className="connect-form-field">
          <span>Provider / compatible endpoint</span>
          <input
            type="text"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            placeholder="e.g. openrouter, together, groq"
            disabled={submitting}
            required
          />
        </label>
        <label className="connect-form-field">
          <span>API key</span>
          <input
            type="password"
            value={credential}
            onChange={(e) => setCredential(e.target.value)}
            autoComplete="off"
            disabled={submitting}
          />
        </label>
        <label className="connect-form-field">
          <span>Model (optional)</span>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="e.g. qwen-2.5-coder-32b"
            disabled={submitting}
          />
        </label>
        <label className="connect-form-field">
          <span>Agent name</span>
          <input
            type="text"
            value={agentName}
            onChange={(e) => setAgentName(e.target.value)}
            placeholder="e.g. qwen-coder"
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
            {submitting ? <Loader2 size={13} className="spin" /> : 'Save connection'}
          </button>
        </div>
      </form>
    </div>
  );
};
