import React, { createContext, useContext, useState, useEffect } from 'react';
import type { ExtensionMessage } from '../types/messages';

interface ExtensionContextType {
  isConnected: boolean;
  lastMessage: string | undefined;
}

const ExtensionContext = createContext<ExtensionContextType>({
  isConnected: false,
  lastMessage: undefined,
});

export const ExtensionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<string | undefined>(undefined);

  useEffect(() => {
    const handleMessage = (event: MessageEvent<ExtensionMessage>) => {
      const data = event.data;
      if (data && data.type === 'INIT') {
        setIsConnected(true);
        setLastMessage('Connected to Extension');
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  return (
    <ExtensionContext.Provider value={{ isConnected, lastMessage }}>
      {children}
    </ExtensionContext.Provider>
  );
};

export const useExtensionContext = () => useContext(ExtensionContext);
