// Shared Playwright helpers for the e2e smoke layer.
//
// None of these tests should ever depend on a live backend: `src/lib/api.js`
// falls back to `https://api.iema.ai` when VITE_BACKEND_URL isn't set (which
// it isn't in this repo/CI), and `TemplateGallery.jsx` calls
// `${import.meta.env.VITE_BACKEND_URL}/api/builder/templates` which — with
// no env var set — resolves to a same-origin `/undefined/api/...` request.
// `mockBackend` intercepts both at the browser level (Playwright route
// interception) so every test runs fully offline and deterministically,
// regardless of which page happens to fire a request on mount.
export async function mockBackend(page) {
  await page.route('https://api.iema.ai/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  );
  await page.route('**/undefined/api/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"items": []}' }),
  );
}
