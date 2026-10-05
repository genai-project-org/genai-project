import { describe, expect, test } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/test-utils';
import ThemeToggle from './ThemeToggle';

// Radix's DropdownMenu opens on pointerdown (not a plain click), and its
// Popper content keeps repositioning itself every animation frame for as
// long as it stays mounted — in jsdom that polling has no real layout to
// settle against, so any `await` (e.g. userEvent's built-in delays, or
// `findBy*`) gives it room to run and the test balloons to several
// seconds. Firing pointerdown/pointerup synchronously and asserting with
// the non-async `getBy*` queries keeps these tests fast and deterministic.
function openMenu(trigger) {
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: 'mouse' });
  fireEvent.pointerUp(trigger, { button: 0, pointerType: 'mouse' });
}

describe('ThemeToggle', () => {
  test('dispatches setTheme("light") when Light is chosen', () => {
    const { store } = renderWithProviders(<ThemeToggle />, {
      preloadedState: { ui: { theme: 'dark', sidebarCollapsed: false, walletBalance: null } },
    });

    openMenu(screen.getByTestId('theme-toggle'));
    fireEvent.click(screen.getByText('Light'));

    expect(store.getState().ui.theme).toBe('light');
  });

  test('dispatches setTheme("system") when System is chosen', () => {
    const { store } = renderWithProviders(<ThemeToggle />, {
      preloadedState: { ui: { theme: 'light', sidebarCollapsed: false, walletBalance: null } },
    });

    openMenu(screen.getByTestId('theme-toggle'));
    fireEvent.click(screen.getByText('System'));

    expect(store.getState().ui.theme).toBe('system');
  });
});
