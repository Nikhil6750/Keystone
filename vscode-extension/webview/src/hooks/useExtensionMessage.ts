import { useExtensionContext } from '../context/ExtensionContext';

export function useExtensionMessage() {
  return useExtensionContext();
}
