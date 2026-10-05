// Playwright e2e smoke layer. These are deliberately shallow: they exercise
// the app through a real browser against the Vite dev server (see
// playwright.config.js) to catch things unit/component tests can't —
// routing wiring, the production HTML shell, and cross-component
// integration — without asserting on business logic (that's the Vitest
// layer's job). Every test mocks the backend at the network boundary via
// `mockBackend` (see ./fixtures.js), so none of them require, or can
// accidentally reach, a real server.
import { test, expect } from '@playwright/test';
import { mockBackend } from './fixtures.js';

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
});

test('the app loads without crashing and renders the landing page', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err));

  await page.goto('/');

  await expect(page).toHaveTitle(/supercreater\.ai/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('learn');
  expect(pageErrors).toEqual([]);
});

test('primary navigation: "Get started" leads to the registration form', async ({ page }) => {
  await page.goto('/');

  await page.getByTestId('home-get-started-btn').click();

  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible();
});

test('primary navigation: "Sign in" leads to the login form', async ({ page }) => {
  await page.goto('/');

  await page.locator('a[href="/login"]').click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
});

test('a key form (login) renders its required fields', async ({ page }) => {
  await page.goto('/login');

  const email = page.getByTestId('auth-email-input');
  const password = page.getByTestId('auth-password-input');

  await expect(email).toBeVisible();
  await expect(password).toBeVisible();
  await expect(email).toHaveAttribute('required', '');
  await expect(password).toHaveAttribute('required', '');
  await expect(page.getByTestId('auth-submit-btn')).toBeVisible();
});

test('the "Forgot password?" link leads to the recovery flow', async ({ page }) => {
  await page.goto('/login');

  await page.getByTestId('auth-forgot-link').click();

  await expect(page).toHaveURL(/\/forgot-password$/);
  await expect(page.getByTestId('forgot-email-input')).toBeVisible();
});

test('unknown routes redirect back to the landing page', async ({ page }) => {
  await page.goto('/this-route-does-not-exist');

  await expect(page).toHaveURL('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('learn');
});
