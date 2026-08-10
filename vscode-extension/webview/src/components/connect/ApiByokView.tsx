import React from 'react';
import { ArrowLeft } from 'lucide-react';
import type { CategoryDetailViewProps } from './InstalledSignInView';

const FUTURE_STEPS = ['Provider / compatible endpoint', 'Credential setup', 'Model', 'Agent name', 'Capabilities'];

/**
 * API/BYOK connection setup (one provider connection -> many Keystone
 * agents, e.g. `openrouter-personal` -> `qwen-coder` + `qwen-reviewer`).
 *
 * IMPORTANT: this view intentionally has no functional credential input.
 * The backend credential/connection API is not ready, and the product
 * rule for this stage is explicit: never place an API key into React
 * state, localStorage, `workspaceState`, VS Code settings, logs, or an
 * orchestration payload. If credential entry is implemented later, it
 * must go through the extension-host boundary and VS Code
 * `SecretStorage` -- never handled directly in this webview. Showing the
 * future step list here is documentation, not a working form.
 */
export const ApiByokView: React.FC<CategoryDetailViewProps> = ({ onBack }) => {
  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onBack}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">API / BYOK</h2>
      <div className="connect-category-detail">
        <span className="connect-unavailable-badge">Not yet available</span>
        <p>
          Bring-your-own-key provider connections are not available in this build. One
          connection (e.g. an OpenRouter account) will be able to create multiple
          Keystone agents, each with its own name, model, and capabilities.
        </p>
        <p>
          Credentials will never be stored in this webview -- entry will go through VS
          Code&apos;s secure secret storage once the backend connection API is ready.
        </p>
        <ol className="connect-future-steps" aria-label="Future setup steps (preview only)">
          {FUTURE_STEPS.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
    </div>
  );
};
