import React from 'react';
import { ExtensionProvider } from './context/ExtensionContext';
import { MainPage } from './pages/MainPage';
import './styles/globals.css';

export const App: React.FC = () => {
  return (
    <ExtensionProvider>
      <MainPage />
    </ExtensionProvider>
  );
};

export default App;
