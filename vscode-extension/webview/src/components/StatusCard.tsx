import React from 'react';
import { useExtensionMessage } from '../hooks/useExtensionMessage';

export const StatusCard: React.FC = () => {
  const { isConnected, lastMessage } = useExtensionMessage();

  return (
    <div className="card">
      <h1>Keystone</h1>
      <p>Extension successfully initialized.</p>
      <p>Sprint 1 Foundation Complete.</p>
      <div className={`status-badge ${isConnected ? 'connected' : ''}`}>
        {lastMessage || 'Connecting to Extension...'}
      </div>
    </div>
  );
};
