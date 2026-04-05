import { test, expect } from './fixtures.js';

test('live terminal can be stopped from the session page when available', async ({ page, server }) => {
  const sessionName = 'live-runner';
  await server.addSession(sessionName);
  const { baseURL } = await server.start();
  const encoded = encodeURIComponent(sessionName);

  const startResponse = await page.request.post(
    `${baseURL}/api/session/${encoded}/terminal/start`,
  );
  const startJson = await startResponse.json();
  if (startJson.error) {
    test.skip(`Terminal not available in this environment: ${startJson.error}`);
  }

  await page.goto(`${baseURL}/session/${encoded}`);

  const openRequest = page.waitForResponse((response) => {
    return response.request().method() === 'POST'
      && response.url().endsWith(`/api/session/${encoded}/terminal/start`);
  });
  await page.getByRole('button', { name: 'Open Terminal' }).click();
  await openRequest;
  await expect(page.getByRole('button', { name: 'Stop Terminal' })).toBeVisible();

  const stopRequest = page.waitForResponse((response) => {
    return response.request().method() === 'POST'
      && response.url().endsWith(`/api/session/${encoded}/terminal/stop`);
  });
  await page.getByRole('button', { name: 'Stop Terminal' }).click();
  await stopRequest;

  const readJson = await page.request
    .get(`${baseURL}/api/session/${encoded}/terminal/read`)
    .then((r) => r.json());
  expect(readJson.alive).toBeFalsy();
});
