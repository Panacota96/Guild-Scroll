# Playwright UI Coverage

## Behavior and UX
- **Delete session (codex):** Clicking the Delete button issues a `DELETE /api/session/<name>` request, removes the session directory, and the codex refreshes without the card.
- **Delete session (session page):** The Delete Session action triggers the same API call and returns to the codex view with the session removed.
- **Live terminal toggle:** The session page uses **Open/Stop Terminal** to manage the live PTY. The flow requires `zsh` on the host; when unavailable the Playwright test skips and the close-live-session capability remains missing in that environment.

## Test plan
- `e2e/delete-session.spec.js` checks deletion from the codex and from a session page, asserting both UI removal and backend deletion.
- `e2e/live-session.spec.js` exercises the live terminal start/stop flow when supported; it skips with a clear reason if `zsh` is absent.
- Tests run against a throwaway `GUILD_SCROLL_DIR` to avoid touching real sessions.

## Security and performance notes
- Tests spin up `gscroll serve` bound to `127.0.0.1` on a random port and never reach external networks.
- Headless Chromium only; browsers are downloaded via `npx playwright install chromium`.
- Session data lives under a temporary directory that is deleted after each run.

## Running Playwright tests
```bash
npm install              # installs Playwright + types
npx playwright install chromium
npm run test:e2e -- --project=chromium
# For headed runs
npm run test:e2e:headed -- --project=chromium
```

If `zsh` is missing, the live-session test will skip; install `zsh` to validate the close-live-session path.
