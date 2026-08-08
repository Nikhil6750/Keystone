# Keystone VS Code Extension — Architecture & Runtime Foundation

The **Keystone VS Code Extension** provides the developer-facing IDE integration layer for the Keystone AI Agent Orchestration Platform.

---

## 🏗️ System Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                    VS Code IDE Host                     │
│                                                         │
│   ┌─────────────────────────────────────────────────┐   │
│   │               Activity Bar / Sidebar            │   │
│   └────────────────────────┬────────────────────────┘   │
│                            │                            │
│   ┌────────────────────────▼────────────────────────┐   │
│   │              Extension Runtime Host             │   │
│   │  (commands, lifecycle, providers, messaging)    │   │
│   └────────────────────────┬────────────────────────┘   │
│                            │                            │
│                  postMessage Bridge                     │
│                            │                            │
│   ┌────────────────────────▼────────────────────────┐   │
│   │              React Webview Panel                │   │
│   │           (Vite + React 18 App)                 │   │
│   └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 Folder Structure

```text
vscode-extension/
├── src/
│   ├── core/
│   │   ├── activation/      # Extension activation sequence
│   │   ├── configuration/   # Workspace settings manager
│   │   └── lifecycle/       # Subscriptions and teardown handling
│   ├── commands/            # Registered VS Code commands
│   ├── providers/
│   │   ├── activity-bar/    # Activity bar container configuration
│   │   ├── sidebar/         # Sidebar WebviewViewProvider implementation
│   │   └── status-bar/      # Keystone Status Bar item
│   ├── messaging/           # Two-way postMessage communication bridge
│   ├── controllers/         # Webview panel & workspace orchestration
│   ├── services/            # Extension host service layer
│   ├── api/                 # Engine client contracts integration
│   ├── utils/               # OutputChannel logging utilities
│   └── extension.ts         # Extension entry point (activate/deactivate)
├── webview/                 # Independent React + Vite webview app
│   ├── src/
│   │   ├── components/      # Webview UI components
│   │   ├── hooks/           # Extension message listener hooks
│   │   ├── pages/           # Main Webview pages
│   │   ├── styles/          # VS Code theme-compatible CSS
│   │   ├── assets/          # SVG assets
│   │   ├── context/         # Extension state React context
│   │   ├── services/        # acquireVsCodeApi wrapper
│   │   ├── types/           # Webview message contracts
│   │   └── App.tsx          # Main React application root
│   ├── index.html           # HTML container template
│   ├── package.json         # Webview dependencies (React, Vite)
│   ├── tsconfig.json        # Webview TypeScript configuration
│   └── vite.config.ts       # Vite build configuration
├── package.json             # Extension manifest & scripts
├── tsconfig.json            # Extension TypeScript configuration
└── README.md                # Architecture documentation
```

---

## 🔄 Extension Lifecycle

1. **Activation**: VS Code triggers `activate(context)` upon command execution (`keystone.openWorkspace`) or sidebar view visibility (`keystone.sidebarView`).
2. **Registration**:
   - Status Bar item is initialized and placed in the lower-right workspace status bar.
   - Sidebar WebviewViewProvider is registered to populate the Activity Bar sidebar.
   - Command `keystone.openWorkspace` is registered to launch the React Webview Panel.
3. **Execution**: Running `Keystone: Open Workspace` creates or reveals a `WebviewPanel` hosting the built React webview.
4. **Deactivation**: `deactivate()` disposes of status bar items, event listeners, and active webview panels cleanly.

---

## 💬 Messaging Architecture

The Extension Host and React Webview communicate asynchronously over VS Code's `postMessage` bridge:

- **Extension Host $\rightarrow$ Webview**:
  ```ts
  panel.webview.postMessage({ type: 'INIT', message: 'Extension Ready' });
  ```
- **Webview $\rightarrow$ Extension Host**:
  ```ts
  window.addEventListener('message', (event) => { ... });
  ```

---

## 🚀 How to Run & Debug

### 1. Build Extension & Webview
```bash
cd vscode-extension
npm run build
```

### 2. Launch Extension in VS Code
- Open `vscode-extension` in VS Code.
- Press **F5** (or run `Extension` launch configuration).
- A new **Extension Development Host** window opens.

### 3. Verify Features
- Verify the **Keystone** icon appears in the Activity Bar.
- Verify the **Keystone Explorer** opens in the Sidebar.
- Verify the **Keystone Status Bar** item appears at the bottom.
- Run Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`) $\rightarrow$ **`Keystone: Open Workspace`**.
- Confirm Webview renders `Extension successfully initialized.` and `Connected to Extension`.
