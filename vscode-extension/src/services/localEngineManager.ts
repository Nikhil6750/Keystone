import * as net from 'net';
import { ChildProcess, spawn } from 'child_process';
import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

const HEALTH_URL = 'http://127.0.0.1:8000/api/v1/health';
const ENGINE_HOST = '127.0.0.1';
const ENGINE_PORT = 8000;
const HEALTH_CHECK_TIMEOUT_MS = 2000;
const PORT_PROBE_TIMEOUT_MS = 1000;
const START_POLL_INTERVAL_MS = 500;
const START_TIMEOUT_MS = 30000;

export type EngineEnsureResult =
  | 'already_healthy'
  | 'started'
  | 'unconfigured'
  | 'port_conflict'
  | 'failed_to_start';

/**
 * Auto-manages the local Keystone backend process so the product never
 * again requires "open a terminal and run uvicorn yourself" (Stage 8C.3,
 * Part 9 -- this exact failure mode recurred repeatedly before this).
 *
 * Safety, deliberately narrow:
 * - Only ever spawns the one explicit, user-configured
 *   `keystone.engine.command` in `keystone.engine.cwd` -- never a shell
 *   string (`shell: false`, argv split, no interpolation), and never
 *   anything the webview supplies.
 * - Never starts a second engine process if one it already started is
 *   still alive, and never starts anything at all if the port already
 *   answers a real health check.
 * - Never kills whatever already owns port 8000 if it doesn't look like
 *   Keystone -- reports a conflict instead, so the user can resolve it.
 * - Unconfigured (`keystone.engine.command`/`cwd` empty, the honest
 *   out-of-the-box default -- this extension does not bundle a Python
 *   backend) is a normal, reported outcome, never a silent no-op.
 */
export class LocalEngineManager implements vscode.Disposable {
  private child: ChildProcess | null = null;
  private inFlight: Promise<EngineEnsureResult> | null = null;

  public async ensureRunning(): Promise<EngineEnsureResult> {
    if (this.inFlight) {
      return this.inFlight;
    }
    this.inFlight = this.ensureRunningInternal();
    try {
      return await this.inFlight;
    } finally {
      this.inFlight = null;
    }
  }

  private async ensureRunningInternal(): Promise<EngineEnsureResult> {
    if (await this.isHealthy()) {
      return 'already_healthy';
    }

    if (this.child !== null && this.child.exitCode === null) {
      // We already have a starting/started child -- wait for it rather
      // than spawning a duplicate.
      return this.waitForHealthy();
    }

    const config = vscode.workspace.getConfiguration('keystone');
    const command = config.get<string>('engine.command', '').trim();
    const cwd = config.get<string>('engine.cwd', '').trim();
    if (!command || !cwd) {
      Logger.info(
        'Local engine auto-start skipped: keystone.engine.command / keystone.engine.cwd not configured'
      );
      return 'unconfigured';
    }

    if (await this.isPortOpen()) {
      Logger.error(
        `Port ${ENGINE_PORT} is already in use by another service (did not answer the Keystone health check).`
      );
      return 'port_conflict';
    }

    const [executable, ...args] = command.split(/\s+/).filter(Boolean);
    if (!executable) {
      Logger.error('keystone.engine.command is set but could not be parsed into a command.');
      return 'unconfigured';
    }

    Logger.info(`Starting local Keystone engine: ${command} (cwd=${cwd})`);
    try {
      this.child = spawn(executable, args, { cwd, shell: false, stdio: 'ignore' });
    } catch (err) {
      Logger.error('Failed to start the local Keystone engine process', err);
      this.child = null;
      return 'failed_to_start';
    }
    this.child.on('exit', (code) => {
      Logger.info(`Local Keystone engine process exited (code=${String(code)})`);
      this.child = null;
    });
    this.child.on('error', (err) => {
      Logger.error('Local Keystone engine process error', err);
    });

    const healthy = await this.waitForHealthy();
    return healthy === 'already_healthy' ? 'started' : healthy;
  }

  private async waitForHealthy(): Promise<EngineEnsureResult> {
    const deadline = Date.now() + START_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (await this.isHealthy()) {
        Logger.info('Local Keystone engine is healthy.');
        return 'already_healthy';
      }
      await new Promise((resolve) => setTimeout(resolve, START_POLL_INTERVAL_MS));
    }
    Logger.error(`Local Keystone engine did not become healthy within ${START_TIMEOUT_MS}ms.`);
    return 'failed_to_start';
  }

  private async isHealthy(): Promise<boolean> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);
    try {
      const response = await fetch(HEALTH_URL, { signal: controller.signal });
      return response.ok;
    } catch {
      return false;
    } finally {
      clearTimeout(timeout);
    }
  }

  /** True if *something* accepts a TCP connection on the engine port,
   * even though it didn't pass the HTTP health check above -- the signal
   * used to distinguish "nothing is listening yet" from "a different
   * service already owns this port," which must never be killed. */
  private isPortOpen(): Promise<boolean> {
    return new Promise((resolve) => {
      const socket = net.createConnection({ host: ENGINE_HOST, port: ENGINE_PORT });
      const finish = (open: boolean): void => {
        socket.removeAllListeners();
        socket.destroy();
        resolve(open);
      };
      socket.setTimeout(PORT_PROBE_TIMEOUT_MS);
      socket.once('connect', () => finish(true));
      socket.once('timeout', () => finish(false));
      socket.once('error', () => finish(false));
    });
  }

  /** Stops the engine process only if this manager started it -- never
   * touches a pre-existing or externally-owned process. */
  public dispose(): void {
    if (this.child && this.child.exitCode === null) {
      Logger.info('Stopping local Keystone engine process owned by this extension session.');
      this.child.kill();
    }
    this.child = null;
  }
}
