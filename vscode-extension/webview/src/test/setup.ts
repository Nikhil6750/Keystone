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

// jsdom does not implement EventSource -- tests that exercise SSE mock
// `subscribeToOrchestrationEvents` directly instead of relying on a real
// EventSource implementation.
if (typeof window.EventSource === 'undefined') {
  class NoopEventSource {
    public close(): void {
      /* no-op */
    }
    public addEventListener(): void {
      /* no-op */
    }
  }
  // @ts-expect-error -- minimal test-only stand-in, not a spec-complete EventSource
  window.EventSource = NoopEventSource;
}
