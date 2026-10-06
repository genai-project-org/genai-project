// Verifies the Excalidraw architecture-diagram canvas added to HLD design
// problems actually renders and is interactive in a real browser — draw a
// rectangle, an arrow, and a text label, using Excalidraw's own toolbar
// (this component doesn't build a custom one, see DesignDiagramCanvas.jsx).
//
// Unlike smoke.spec.js, this test intentionally talks to the REAL local
// backend (apps/api's dev server on http://127.0.0.1:8001, per .env.local's
// VITE_BACKEND_URL) rather than mocking it: registering a throwaway user
// and hitting the real `sd-url-shortener` problem (which has
// supports_diagram: true) is simpler and more meaningful here than
// hand-mocking the whole problem-detail response shape, and the point of
// THIS test is purely "does the canvas render/behave in a browser" — the
// grading pipeline's correctness (including that the vision-based grader
// genuinely reacts to what's drawn) is verified separately via direct API
// calls against the real backend, not through this browser test.
import { test, expect } from '@playwright/test';

const BACKEND_URL = 'http://127.0.0.1:8001';

test.describe('Practice design diagram canvas', () => {
  test('renders an Excalidraw canvas and accepts drawn shapes/text', async ({ page, request }) => {
    // Auth against the real backend with a fixed reusable test account —
    // logging in (not registering a fresh user every run) matters here
    // specifically because /auth/register is rate-limited to 5/hour, which
    // a throwaway-user-per-run strategy would burn through immediately
    // across a handful of local test iterations.
    const email = 'siddharth.bose+practicedesigntest@iemlabs.com';
    const password = 'TestPass123!';
    let authResp = await request.post(`${BACKEND_URL}/api/auth/login`, { data: { email, password } });
    if (!authResp.ok()) {
      authResp = await request.post(`${BACKEND_URL}/api/auth/register`, {
        data: { email, password, name: 'Practice Design Tester' },
      });
    }
    expect(authResp.ok()).toBeTruthy();
    const { user, tokens } = await authResp.json();

    // Seed localStorage the same way authSlice.js reads it back on load —
    // same-origin write requires having navigated to the app first.
    await page.goto('/login');
    await page.evaluate(
      ([u, t]) => localStorage.setItem('iema_auth', JSON.stringify({ user: u, tokens: t })),
      [user, tokens]
    );

    await page.goto('/practice?problem=sd-url-shortener');

    // The design statement pane confirms the right problem loaded (an HLD
    // problem with supports_diagram: true) before asserting on the canvas.
    await expect(page.getByTestId('practice-design-statement')).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('heading', { name: 'Design a URL Shortener' })).toBeVisible();

    const canvas = page.getByTestId('diagram-canvas');
    await expect(canvas).toBeVisible();
    // Excalidraw's own root element + toolbar actually mounted, not just our wrapper div.
    await expect(canvas.locator('.excalidraw')).toBeVisible({ timeout: 15000 });

    const box = await canvas.boundingBox();

    // Draw a rectangle via Excalidraw's own keyboard shortcut ('r') + drag —
    // the core "can a first-time user do the basic thing" interaction, using
    // Excalidraw's shipped toolbar/shortcuts rather than any custom UI.
    await page.mouse.click(box.x + 10, box.y + 10);
    await page.keyboard.press('r');
    await page.mouse.move(box.x + 60, box.y + 60);
    await page.mouse.down();
    await page.mouse.move(box.x + 220, box.y + 160, { steps: 10 });
    await page.mouse.up();
    // Excalidraw renders two stacked canvases (a "static" content layer and
    // an "interactive" layer for selection/cursors) — `.first()` since this
    // just confirms Excalidraw's own canvas actually mounted, not which layer.
    await expect(canvas.locator('.excalidraw__canvas').first()).toBeVisible();

    // Draw an arrow ('a' shortcut).
    await page.keyboard.press('a');
    await page.mouse.move(box.x + 260, box.y + 100);
    await page.mouse.down();
    await page.mouse.move(box.x + 380, box.y + 100, { steps: 10 });
    await page.mouse.up();

    // Add a text label ('t' shortcut), type into Excalidraw's own text-editing
    // overlay (a real contenteditable-backed textarea while editing), then
    // commit it by clicking elsewhere on the canvas.
    await page.keyboard.press('t');
    await page.mouse.click(box.x + 90, box.y + 90);
    const textEditor = page.locator('.excalidraw-textEditorContainer textarea');
    await expect(textEditor).toBeVisible();
    await textEditor.fill('Load Balancer');
    await page.mouse.click(box.x + 400, box.y + 300);

    // The text-editing textarea itself hides once the label is committed
    // (Excalidraw keeps the container in the DOM but stops showing the
    // editor) — the app (and Excalidraw itself) is still alive/interactive
    // after all four drawing interactions above.
    await expect(textEditor).not.toBeVisible();
    await expect(page.locator('.excalidraw')).toBeVisible();

    // Calculation scratchpad renders alongside the diagram for this problem
    // too (also supports_calculation: true) — confirm it's there and the
    // inline safe-arithmetic evaluation works.
    const calcTextarea = page.getByTestId('practice-calculation-textarea');
    await expect(calcTextarea).toBeVisible();
    await calcTextarea.fill('100e6 / 86400');
    await expect(page.getByTestId('practice-calculation-live-result')).toContainText('1,157');
  });
});
