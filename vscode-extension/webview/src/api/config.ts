/**
 * Keystone backend connection configuration.
 *
 * The webview talks to the local Keystone backend directly via `fetch`/
 * `EventSource` (not proxied through the extension host) -- this requires
 * the webview's Content-Security-Policy to explicitly allow `connect-src`
 * to the loopback address (see `src/webview/getWebviewHtml.ts` on the
 * extension-host side). No other host is ever contacted.
 *
 * Not yet user-configurable via a VS Code setting -- a fixed local default
 * is deliberately the only supported value for this stage; wiring a real
 * setting is future work, not faked here.
 */
export const KEYSTONE_API_BASE_URL = 'http://localhost:8000';

export const KEYSTONE_API_PREFIX = '/api/v1';
