interface VsCodeApi {
  postMessage(message: unknown): void;
  setState(state: unknown): void;
  getState(): unknown;
}

declare function acquireVsCodeApi(): VsCodeApi;

/**
 * Strict singleton wrapper around VS Code's acquireVsCodeApi().
 * Guarantees acquireVsCodeApi() is invoked at most once per Webview lifecycle.
 */
class VsCodeApiWrapper {
  private static instance: VsCodeApiWrapper | undefined;
  private api: VsCodeApi | undefined;

  private constructor() {
    try {
      if (typeof acquireVsCodeApi === 'function') {
        this.api = acquireVsCodeApi();
      }
    } catch {
      // Safely ignore if acquireVsCodeApi was already called or unavailable
    }
  }

  public static getInstance(): VsCodeApiWrapper {
    if (!VsCodeApiWrapper.instance) {
      VsCodeApiWrapper.instance = new VsCodeApiWrapper();
    }
    return VsCodeApiWrapper.instance;
  }

  public postMessage(message: unknown): void {
    this.api?.postMessage(message);
  }

  public getState(): unknown {
    return this.api?.getState();
  }

  public setState(state: unknown): void {
    this.api?.setState(state);
  }
}

export const vscodeApi = VsCodeApiWrapper.getInstance();
