import path from 'node:path';
import fs from 'node:fs/promises';
import { test, expect } from './fixtures.js';

test('deleting from the session codex removes the card and backend data', async ({ page, server }) => {
  await server.addSession('alpha-run', { command_count: 3 });
  await server.addSession('beta-run', { command_count: 1 });
  const { baseURL, sessionsDir } = await server.start();

  await page.addInitScript(() => {
    window.confirm = () => true;
  });
  await page.goto(`${baseURL}/`);

  const initial = await page.request.get(`${baseURL}/api/sessions`).then((r) => r.json());
  expect(initial.sessions.map((s) => s.session_name)).toEqual(
    expect.arrayContaining(['alpha-run', 'beta-run']),
  );

  const targetCard = page.locator('.session-card', { hasText: 'alpha-run' });
  await expect(targetCard).toBeVisible();

  const deleteRequest = page.waitForRequest((req) => {
    return req.method() === 'DELETE' && req.url().includes('/api/session/alpha-run');
  });
  await targetCard.getByRole('button', { name: 'Delete' }).click();
  await deleteRequest;

  await expect.poll(
    async () => {
      const sessions = await page.request.get(`${baseURL}/api/sessions`).then((r) => r.json());
      return sessions.sessions.some((s) => s.session_name === 'alpha-run');
    },
    { timeout: 15000, message: 'alpha-run should be removed from API' },
  ).toBeFalsy();

  await page.reload();
  await expect(page.locator('.session-card', { hasText: 'alpha-run' })).toHaveCount(0, {
    timeout: 15000,
  });

  const sessions = await page.request.get(`${baseURL}/api/sessions`).then((r) => r.json());
  expect(sessions.sessions.map((s) => s.session_name)).not.toContain('alpha-run');
  await expect(async () => fs.access(path.join(sessionsDir, 'alpha-run'))).rejects.toThrow();
});

test('deleting from a session page redirects home and removes the session', async ({ page, server }) => {
  const sessionName = 'gamma-run';
  await server.addSession(sessionName, { hostname: 'deletion-host' });
  const { baseURL, sessionsDir } = await server.start();
  const encoded = encodeURIComponent(sessionName);

  await page.addInitScript(() => {
    window.confirm = () => true;
  });
  await page.goto(`${baseURL}/session/${encoded}`);

  const initial = await page.request.get(`${baseURL}/api/sessions`).then((r) => r.json());
  expect(initial.sessions.map((s) => s.session_name)).toContain(sessionName);

  const deleteRequest = page.waitForRequest((req) => {
    return req.method() === 'DELETE' && req.url().includes(`/api/session/${encoded}`);
  });
  await page.getByRole('button', { name: 'Delete Session' }).click();
  await deleteRequest;

  await expect.poll(
    async () => {
      const sessions = await page.request.get(`${baseURL}/api/sessions`).then((r) => r.json());
      return sessions.sessions.some((s) => s.session_name === sessionName);
    },
    { timeout: 15000, message: 'session should be removed from API' },
  ).toBeFalsy();

  await page.goto(`${baseURL}/`);
  await expect(page.locator('.session-card', { hasText: sessionName })).toHaveCount(0, {
    timeout: 15000,
  });

  const sessions = await page.request.get(`${baseURL}/api/sessions`).then((r) => r.json());
  expect(sessions.sessions.map((s) => s.session_name)).not.toContain(sessionName);
  await expect(async () => fs.access(path.join(sessionsDir, sessionName))).rejects.toThrow();
});
