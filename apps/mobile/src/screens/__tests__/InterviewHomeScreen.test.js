/**
 * Component tests for InterviewHomeScreen — mirrors WalletScreen.test.js's
 * conventions (RTL + `jest.mock` so no real HTTP call happens), but this
 * screen also reads/writes `interviewSlice` state, so it's wrapped in a
 * real `react-redux` Provider backed by a minimal store containing just
 * that slice (no need to pull in the full app store / native SecureStore
 * dependency chain that `authSlice` carries).
 */
import React from 'react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, fireEvent } from '@testing-library/react-native';
import InterviewHomeScreen from '../InterviewHomeScreen';
import interviewReducer from '../../store/slices/interviewSlice';
import * as interviewApi from '../../services/interviewApi';

jest.mock('../../services/interviewApi');
jest.mock('../../api', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
jest.mock('expo-web-browser', () => ({ openBrowserAsync: jest.fn() }));

function renderWithStore(navigation = { navigate: jest.fn(), toggleDrawer: jest.fn() }) {
  const store = configureStore({ reducer: { interview: interviewReducer } });
  render(
    <Provider store={store}>
      <InterviewHomeScreen navigation={navigation} />
    </Provider>
  );
  return { store, navigation };
}

describe('InterviewHomeScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows entitlement (aggregate + per-grant), session history and packs once loaded', async () => {
    interviewApi.getEntitlement.mockResolvedValue({
      sessions_remaining: 2,
      grants: [
        {
          grant_id: 'g1',
          pack_slug: 'starter',
          pack_name: 'Starter Pack',
          sessions_total: 3,
          sessions_remaining: 2,
          config: {
            technical_minutes: 30,
            behavioral_minutes: 0,
            topics: ['hld', 'lld', 'design', 'hr'],
            seniority_levels: ['entry', 'mid'],
            languages: [],
            sub_topics: {},
          },
        },
      ],
    });
    interviewApi.listSessions.mockResolvedValue({
      items: [
        { id: 's1', topic: 'hr', status: 'completed', created_at: '2026-01-01T00:00:00Z', final_report_id: 'r1' },
      ],
    });
    interviewApi.listInterviewPacks.mockResolvedValue({
      items: [{ slug: 'starter', name: 'Starter Pack', price: 19, sessions_included: 3, is_popular: false }],
    });

    renderWithStore();

    await waitFor(() => expect(screen.getByText('2')).toBeTruthy());
    expect(screen.getByText('Starter Pack: 2 of 3 left')).toBeTruthy();
    expect(screen.getByText('hr')).toBeTruthy();
    expect(screen.getAllByText('Starter Pack').length).toBeGreaterThan(0);
  });

  it('shows an empty state when there is no session history', async () => {
    interviewApi.getEntitlement.mockResolvedValue({ sessions_remaining: 0, grants: [] });
    interviewApi.listSessions.mockResolvedValue({ items: [] });
    interviewApi.listInterviewPacks.mockResolvedValue({ items: [] });

    renderWithStore();

    await waitFor(() => expect(screen.getByText('No interviews yet.')).toBeTruthy());
  });

  it('navigates to InterviewSetup when starting a new interview with sessions remaining', async () => {
    interviewApi.getEntitlement.mockResolvedValue({
      sessions_remaining: 3,
      grants: [
        {
          grant_id: 'g1',
          pack_slug: 'prep',
          pack_name: 'Interview Prep Pack',
          sessions_total: 3,
          sessions_remaining: 3,
          config: {
            technical_minutes: 45,
            behavioral_minutes: 15,
            topics: ['dsa', 'hld', 'lld', 'design', 'hr'],
            seniority_levels: ['entry', 'mid', 'senior'],
            languages: ['python'],
            sub_topics: {},
          },
        },
      ],
    });
    interviewApi.listSessions.mockResolvedValue({ items: [] });
    interviewApi.listInterviewPacks.mockResolvedValue({ items: [] });

    const { navigation } = renderWithStore();

    await waitFor(() => expect(screen.getByTestId('interview-start-btn')).toBeTruthy());
    fireEvent.press(screen.getByTestId('interview-start-btn'));

    expect(navigation.navigate).toHaveBeenCalledWith('InterviewSetup');
  });
});
