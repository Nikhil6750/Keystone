import { useContext } from 'react';
import { AppStateContext, type AppStateContextValue } from '../context/AppStateProvider';

export function useAppState(): AppStateContextValue {
  const context = useContext(AppStateContext);
  if (!context) {
    throw new Error('useAppState must be used within an AppStateProvider');
  }
  return context;
}
