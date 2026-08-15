// Guards against the exact regression found in the Antigravity install
// diagnostic: an installed VSIX built before the extension-host backend
// proxy existed, whose webview bundle called `fetch`/`EventSource` directly
// against a hardcoded backend URL. A webview's `vscode-webview://` origin
// can never satisfy backend CORS, so that bundle silently and permanently
// showed "Keystone backend unavailable" even with a healthy, reachable
// backend. Run after `npm run build`, before packaging.

const fs = require('fs');
const path = require('path');

const distExtensionJs = path.join(__dirname, '..', 'dist', 'extension.js');
const backendProxyJs = path.join(__dirname, '..', 'dist', 'api', 'backendProxy.js');
const webviewBundle = path.join(__dirname, '..', 'webview', 'dist', 'assets', 'index.js');

const failures = [];

if (!fs.existsSync(distExtensionJs)) {
  failures.push(`Missing compiled entry point: ${distExtensionJs}`);
}

if (!fs.existsSync(backendProxyJs)) {
  failures.push(`Missing compiled backend proxy: ${backendProxyJs} (extension host cannot relay webview requests)`);
}

if (!fs.existsSync(webviewBundle)) {
  failures.push(`Missing webview bundle: ${webviewBundle}`);
} else {
  const bundle = fs.readFileSync(webviewBundle, 'utf8');

  if (!bundle.includes('KEYSTONE_API_REQUEST')) {
    failures.push('Webview bundle does not reference KEYSTONE_API_REQUEST -- it is not using the postMessage backend proxy.');
  }
  if (!bundle.includes('acquireVsCodeApi')) {
    failures.push('Webview bundle never calls acquireVsCodeApi -- it cannot be talking to the extension host at all.');
  }
  if (/localhost:8000|127\.0\.0\.1:8000/.test(bundle)) {
    failures.push('Webview bundle contains a hardcoded backend URL -- it is calling the backend directly instead of through the extension-host proxy.');
  }
}

if (failures.length > 0) {
  console.error('\nPackage verification failed:\n');
  for (const failure of failures) {
    console.error(`  - ${failure}`);
  }
  console.error('');
  process.exit(1);
}

console.log('Package verification passed: backend proxy present, webview uses postMessage transport only.');
