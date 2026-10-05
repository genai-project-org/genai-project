// Component tests for the app Sidebar: role-gated Admin link, the
// wallet-balance widget, collapsed/expanded layout, logout, and the
// bottom theme switcher. Rendered through renderWithProviders so
// useSelector/useDispatch/NavLink all have real Redux + Router context.
import { describe, expect, test } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/test-utils';
import Sidebar from './Sidebar';
import { NAV } from '@/constants/testIds';

// Radix's DropdownMenu opens on pointerdown, not click, and its Popper
// content keeps repositioning itself every frame in jsdom — see the same
// note in ThemeToggle.test.jsx. Firing pointerdown/up directly keeps this
// deterministic and fast.
function openMenu(trigger) {
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: 'mouse' });
  fireEvent.pointerUp(trigger, { button: 0, pointerType: 'mouse' });
}

const baseUi = { theme: 'dark', sidebarCollapsed: false, walletBalance: null };
const regularUser = { id: 'u1', name: 'Ada Lovelace', email: 'ada@example.invalid', role: 'user' };
const adminUser = { ...regularUser, role: 'admin' };

describe('Sidebar', () => {
  test('does not show the Admin link for a regular user', () => {
    renderWithProviders(<Sidebar />, { preloadedState: { ui: baseUi, auth: { user: regularUser } } });
    expect(screen.queryByTestId(NAV.linkAdmin)).not.toBeInTheDocument();
  });

  test('shows the Admin link when the user has the admin role', () => {
    renderWithProviders(<Sidebar />, { preloadedState: { ui: baseUi, auth: { user: adminUser } } });
    expect(screen.getByTestId(NAV.linkAdmin)).toBeInTheDocument();
  });

  test('hides the wallet widget when walletBalance is null', () => {
    renderWithProviders(<Sidebar />, { preloadedState: { ui: baseUi, auth: { user: regularUser } } });
    expect(screen.queryByTestId('sidebar-wallet-total')).not.toBeInTheDocument();
  });

  test('shows the floored, formatted wallet balance when present', () => {
    renderWithProviders(<Sidebar />, {
      preloadedState: { ui: { ...baseUi, walletBalance: 1234.9 }, auth: { user: regularUser } },
    });
    expect(screen.getByTestId('sidebar-wallet-total')).toHaveTextContent('1,234');
  });

  test('collapsed mode hides text labels like "New Chat"', () => {
    renderWithProviders(<Sidebar />, {
      preloadedState: { ui: { ...baseUi, sidebarCollapsed: true }, auth: { user: regularUser } },
    });
    expect(screen.queryByText('New Chat')).not.toBeInTheDocument();
  });

  test('expanded mode shows text labels like "New Chat"', () => {
    renderWithProviders(<Sidebar />, { preloadedState: { ui: baseUi, auth: { user: regularUser } } });
    expect(screen.getByText('New Chat')).toBeInTheDocument();
  });

  test('the collapse toggle dispatches toggleSidebar', () => {
    const { store } = renderWithProviders(<Sidebar />, {
      preloadedState: { ui: baseUi, auth: { user: regularUser } },
    });
    fireEvent.click(screen.getByTestId(NAV.sidebarToggle));
    expect(store.getState().ui.sidebarCollapsed).toBe(true);
  });

  test('logout clears the auth state', () => {
    const { store } = renderWithProviders(<Sidebar />, {
      preloadedState: {
        ui: baseUi,
        auth: { user: regularUser, access_token: 'tok', refresh_token: 'rtok' },
      },
    });
    fireEvent.click(screen.getByTestId('auth-logout-btn'));
    expect(store.getState().auth.user).toBeNull();
    expect(store.getState().auth.access_token).toBeNull();
  });

  test('choosing Light from the theme menu dispatches setTheme', () => {
    const { store } = renderWithProviders(<Sidebar />, {
      preloadedState: { ui: baseUi, auth: { user: regularUser } },
    });
    openMenu(screen.getByTestId(NAV.themeToggle));
    fireEvent.click(screen.getByText('Light'));
    expect(store.getState().ui.theme).toBe('light');
  });
});
