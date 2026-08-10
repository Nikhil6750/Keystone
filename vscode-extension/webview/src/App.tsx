import React from 'react';
import { ExtensionProvider } from './context/ExtensionContext';
import { KeystoneHome } from './components/home/KeystoneHome';
import './styles/globals.css';

/**
 * Stage 8C.3 UI redesign: the default experience is the single, prompt-
 * first `KeystoneHome` surface -- not the previous tabbed Workflow
 * Builder / Agent Manager / Knowledge / Workspace scaffold (`MainPage`,
 * still present under `pages/` for potential reuse in secondary views,
 * but no longer part of the default path). `AppStateProvider`'s simulated
 * execution pipeline is likewise no longer reachable from here.
 */
export const App: React.FC = () => {
  return (
    <ExtensionProvider>
      <KeystoneHome />
    </ExtensionProvider>
  );
};

export default App;
