/**
 * Component tests for WalletScreen — chosen because it has real conditional
 * rendering worth covering: loading vs loaded balance, empty vs populated
 * transaction list, and positive vs negative transaction styling/iconography.
 *
 * `api` is mocked so no real HTTP call happens (see repo-wide security rule:
 * no real network calls from tests).
 */
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react-native';
import WalletScreen from '../WalletScreen';
import api from '../../api';

jest.mock('../../api', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));

function makeNavigation() {
  return { navigate: jest.fn(), toggleDrawer: jest.fn() };
}

describe('WalletScreen', () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it('shows a placeholder balance while the wallet has not loaded yet', () => {
    // Never resolves within this test — asserts the pre-load render.
    api.get.mockReturnValue(new Promise(() => {}));

    render(<WalletScreen navigation={makeNavigation()} />);

    expect(screen.getByText('—')).toBeTruthy();
  });

  it('renders the total balance and per-bucket credits once the wallet loads', async () => {
    api.get.mockImplementation((path) => {
      if (path === '/wallet/') {
        return Promise.resolve({
          data: {
            total: 1234.9,
            welcome_credits: 100,
            daily_credits: 20,
            bonus_credits: 5,
            referral_credits: 0,
            purchased_credits: 1109.9,
          },
        });
      }
      if (path === '/wallet/transactions') {
        return Promise.resolve({ data: { items: [] } });
      }
      throw new Error(`unexpected path ${path}`);
    });

    render(<WalletScreen navigation={makeNavigation()} />);

    await waitFor(() => expect(screen.getByText('1,234')).toBeTruthy());
    expect(screen.getByText('Purchased')).toBeTruthy();
    expect(screen.getByText('1,109')).toBeTruthy();
  });

  it('shows an empty state when there are no transactions', async () => {
    api.get.mockImplementation((path) => {
      if (path === '/wallet/') return Promise.resolve({ data: { total: 0 } });
      return Promise.resolve({ data: { items: [] } });
    });

    render(<WalletScreen navigation={makeNavigation()} />);

    await waitFor(() => expect(screen.getByText('No transactions yet')).toBeTruthy());
  });

  it('renders a list of transactions, formatting positive and negative amounts differently', async () => {
    api.get.mockImplementation((path) => {
      if (path === '/wallet/') return Promise.resolve({ data: { total: 500 } });
      return Promise.resolve({
        data: {
          items: [
            { id: 't1', amount: 50, description: 'Referral bonus', bucket: 'referral', kind: 'credit' },
            { id: 't2', amount: -12.7, description: 'Chat completion', bucket: 'purchased', kind: 'debit' },
          ],
        },
      });
    });

    render(<WalletScreen navigation={makeNavigation()} />);

    await waitFor(() => expect(screen.getByText('Referral bonus')).toBeTruthy());
    expect(screen.getByText('+50')).toBeTruthy();
    // Math.floor(-12.7) rounds toward -Infinity, i.e. -13 (not a truncating -12).
    expect(screen.getByText('-13')).toBeTruthy();
    expect(screen.getByText('Chat completion')).toBeTruthy();
  });

  it('navigates to the Billing screen when "Recharge wallet" is pressed', async () => {
    api.get.mockResolvedValue({ data: { total: 0, items: [] } });
    const navigation = makeNavigation();

    render(<WalletScreen navigation={navigation} />);

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/wallet/'));
    fireEvent.press(screen.getByText('Recharge wallet →'));

    expect(navigation.navigate).toHaveBeenCalledWith('Billing');
  });
});
