import '@testing-library/jest-dom/vitest';

// The real `acquireVsCodeApi()` only exists inside a VS Code webview host,
// as a global function (not a `Window` property -- see `services/vscodeApi.ts`).
// Provide a minimal, inert stand-in so components that touch
// `vscodeApi` (via `ExtensionContext`) can render under jsdom.
const globalScope = globalThis as unknown as { acquireVsCodeApi?: () => unknown };
if (typeof globalScope.acquireVsCodeApi !== 'function') {
  globalScope.acquireVsCodeApi = () => ({
    postMessage: () => undefined,
    setState: () => undefined,
    getState: () => undefined,
  });
}
