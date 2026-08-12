import React from 'react';
import { WifiOff } from 'lucide-react';

export interface BackendUnavailableProps {
  onRetry: () => void;
  onOpenSettings?: () => void;
}

/**
 * Shown only when the Keystone backend is genuinely unreachable (a real
 * network failure -- see `BackendUnavailableError`). Never simulates or
 * fakes a workflow in this state; the prompt composer is not rendered
 * while this view is active.
 */
export const BackendUnavailable: React.FC<BackendUnavailableProps> = ({
  onRetry,
  onOpenSettings,
}) => {
  return (
    <div className="backend-unavailable-view">
      <WifiOff size={28} className="backend-unavailable-icon" />
      <p className="backend-unavailable-text">Keystone backend unavailable.</p>
      <button type="button" className="btn-retry" onClick={onRetry}>
        Retry
      </button>
      {onOpenSettings && (
        <button type="button" className="btn-link" onClick={onOpenSettings}>
          Open Settings
        </button>
      )}
    </div>
  );
};
