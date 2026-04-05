import { test as base, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';
import { spawn } from 'node:child_process';

async function getAvailablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function waitForServer(proc) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error('Timed out waiting for gscroll web server to start'));
    }, 15000);

    const onReady = (data) => {
      if (settled) return;
      const text = data.toString();
      if (text.includes('Serving on')) {
        settled = true;
        cleanup();
        resolve();
      }
    };

    const onError = (err) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(err instanceof Error ? err : new Error(String(err)));
    };

    const onExit = (code) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error(`gscroll web server exited early (code ${code ?? 'unknown'})`));
    };

    const cleanup = () => {
      clearTimeout(timer);
      proc.stdout?.off('data', onReady);
      proc.stderr?.off('data', onReady);
      proc.off('exit', onExit);
      proc.off('error', onError);
    };

    proc.stdout?.on('data', onReady);
    proc.stderr?.on('data', onReady);
    proc.on('exit', onExit);
    proc.on('error', onError);
  });
}

async function writeSession(sessionsDir, name, overrides = {}) {
  const logsDir = path.join(sessionsDir, name, 'logs');
  await fs.mkdir(logsDir, { recursive: true });
  const meta = {
    type: 'session_meta',
    session_name: name,
    session_id: overrides.session_id ?? 'playwright-e2e',
    start_time: overrides.start_time ?? new Date().toISOString(),
    hostname: overrides.hostname ?? 'localhost',
    command_count: overrides.command_count ?? 1,
    ...overrides,
  };
  const logPath = path.join(logsDir, 'session.jsonl');
  await fs.writeFile(logPath, `${JSON.stringify(meta)}\n`, 'utf-8');
  return logPath;
}

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      window.addEventListener('error', (event) => {
        console.error(
          `window error: ${event.message} at ${event.filename}:${event.lineno}:${event.colno}`,
        );
      });
    });
    page.on('pageerror', (err) => {
      console.error(`page error: ${err.message}\n${err.stack}`);
    });
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const loc = msg.location();
        const location = loc.url
          ? ` (${loc.url}:${loc.lineNumber ?? 0}:${loc.columnNumber ?? 0})`
          : '';
        console.error(`console error: ${msg.text()}${location}`);
      }
    });
    await use(page);
  },
  server: async ({}, use) => {
    const baseDir = await fs.mkdtemp(path.join(os.tmpdir(), 'gscroll-e2e-'));
    const sessionsDir = path.join(baseDir, 'sessions');
    await fs.mkdir(sessionsDir, { recursive: true });

    let serverProc;
    let port;

    const start = async () => {
      if (serverProc) {
        return { baseURL: `http://127.0.0.1:${port}`, port, sessionsDir };
      }
      port = await getAvailablePort();
      const env = {
        ...process.env,
        GUILD_SCROLL_DIR: baseDir,
      };
      if (!env.PYTHONPATH) {
        env.PYTHONPATH = path.join(process.cwd(), 'src');
      } else if (!env.PYTHONPATH.includes(path.join(process.cwd(), 'src'))) {
        env.PYTHONPATH = `${path.join(process.cwd(), 'src')}:${env.PYTHONPATH}`;
      }
      const python = process.env.PYTHON || (os.platform() === 'win32' ? 'python' : 'python3');
      serverProc = spawn(
        python,
        ['-m', 'guild_scroll', 'serve', '--host', '127.0.0.1', '--port', String(port)],
        { env, stdio: ['ignore', 'pipe', 'pipe'] },
      );
      await waitForServer(serverProc);
      return { baseURL: `http://127.0.0.1:${port}`, port, sessionsDir };
    };

    const stop = async () => {
      if (!serverProc) {
        return;
      }
      const proc = serverProc;
      serverProc = undefined;

      if (proc.exitCode !== null || proc.signalCode !== null) {
        return;
      }

      await new Promise((resolve) => {
        const onExit = () => {
          clearTimeout(forceKillTimer);
          resolve();
        };

        const forceKillTimer = setTimeout(() => {
          if (proc.exitCode === null && proc.signalCode === null) {
            proc.kill('SIGKILL');
          }
        }, 5000);

        proc.once('exit', onExit);
        proc.kill('SIGTERM');
      });
    };

    await use({
      baseDir,
      sessionsDir,
      addSession: (name, overrides) => writeSession(sessionsDir, name, overrides),
      start,
      stop,
    });

    await stop();
    await fs.rm(baseDir, { recursive: true, force: true });
  },
});

export { expect };
