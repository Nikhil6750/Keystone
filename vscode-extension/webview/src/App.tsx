import React from 'react';
import { ExtensionProvider } from './context/ExtensionContext';
import { AppStateProvider } from './context/AppStateProvider';
import { NotificationContainer } from './components/notifications/NotificationContainer';
import { MainPage } from './pages/MainPage';
import './styles/globals.css';

export const App: React.FC = () => {
  return (
    <ExtensionProvider>
      <AppStateProvider>
        <NotificationContainer />
        <MainPage />
      </AppStateProvider>
    </ExtensionProvider>
  );
};

export default App;
