// Smoke tests for the contest admin console: every tab renders against a
// realistic /contest/{id}/admin payload, the Save button sends the validated
// settings payload, and create mode offers Quick create + the form tabs.
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ContestAdminPanel from './ContestAdminPanel';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), message: vi.fn() } }));

const adminPayload = {
  id: 'c1', name: 'Demo Contest', status: 'live', state: 'published', archived: false, paused: false,
  start_at: '2026-01-01T10:00:00+00:00', end_at: '2026-01-01T12:00:00+00:00',
  problem_ids: ['two-sum', 'binary-search'],
  problem_configs: { 'two-sum': { points: 50 }, 'binary-search': { points: 150, release_after_minutes: 30 } },
  settings: { scoring: { mode: 'points', first_solve_bonus: 20 }, prizes: [{ from_rank: 1, to_rank: 1, title: 'Champion', prize: 'Trophy' }] },
  invited_emails: [], team_count: 2, participant_count: 3, submission_count: 7,
};

vi.mock('@/lib/api', () => ({
  default: {
    get: vi.fn((url) => {
      if (url === '/practice/roadmap') {
        return Promise.resolve({ data: { items: [
          { id: 'two-sum', title: 'Two Sum', difficulty: 'Easy', step: 'Arrays', question_type: 'code' },
          { id: 'binary-search', title: 'Binary Search', difficulty: 'Medium', step: 'Search', question_type: 'code' },
          { id: 'valid-anagram', title: 'Valid Anagram', difficulty: 'Easy', step: 'Arrays', question_type: 'code' },
        ] } });
      }
      if (url === '/contest/c1/admin') return Promise.resolve({ data: adminPayload });
      if (url === '/contest/templates') return Promise.resolve({ data: { items: [{ id: 'sprint-1h', name: '1-hour sprint', description: 'd' }] } });
      return Promise.resolve({ data: { items: [] } });
    }),
    post: vi.fn(() => Promise.resolve({ data: { id: 'c2' } })),
    patch: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
  },
}));

import api from '@/lib/api';

const openTab = (name) => fireEvent.mouseDown(screen.getByTestId(`contest-tab-${name}`), { button: 0 });

describe('ContestAdminPanel', () => {
  beforeEach(() => vi.clearAllMocks());

  test('edit mode renders all seven tabs and their content', async () => {
    render(<ContestAdminPanel editingContest={{ id: 'c1', name: 'Demo Contest' }} onSaved={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('contest-new-name').value).toBe('Demo Contest'));
    for (const t of ['overview', 'problems', 'scoring', 'participants', 'leaderboard', 'announcements', 'settings']) {
      expect(screen.getByTestId(`contest-tab-${t}`)).toBeTruthy();
    }
    expect(screen.getByTestId('contest-lifecycle')).toBeTruthy();
    expect(screen.getByTestId('contest-pause')).toBeTruthy(); // live contest -> pause available
    expect(screen.getByTestId('contest-stop-btn')).toBeTruthy();

    openTab('problems');
    await waitFor(() => expect(screen.getByTestId('contest-problem-row-binary-search')).toBeTruthy());
    openTab('scoring');
    await waitFor(() => expect(screen.getByTestId('contest-tab-scoring-form')).toBeTruthy());
    openTab('participants');
    await waitFor(() => expect(screen.getByTestId('contest-panel-participants')).toBeTruthy());
    openTab('leaderboard');
    await waitFor(() => expect(screen.getByTestId('lb-visibility')).toBeTruthy());
    openTab('announcements');
    await waitFor(() => expect(screen.getByTestId('contest-panel-announcements')).toBeTruthy());
    openTab('settings');
    await waitFor(() => expect(screen.getByTestId('contest-tab-settings-form')).toBeTruthy());
  });

  test('save sends the full validated payload through PATCH', async () => {
    render(<ContestAdminPanel editingContest={{ id: 'c1', name: 'Demo Contest' }} onSaved={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('contest-new-name').value).toBe('Demo Contest'));
    fireEvent.click(screen.getByTestId('contest-admin-save'));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const [url, body] = api.patch.mock.calls[0];
    expect(url).toBe('/contest/c1');
    expect(body.problem_ids).toEqual(['two-sum', 'binary-search']);
    expect(body.settings.scoring.mode).toBe('points');
    expect(body.settings.scoring.first_solve_bonus).toBe(20);
    expect(body.problem_configs['binary-search'].release_after_minutes).toBe(30);
    expect(body.problem_configs['two-sum'].test_weights).toBeNull();
    expect(body.settings.branding.banner_url).toBeNull();
  });

  test('create mode shows quick-create templates and disables ops tabs until created', async () => {
    render(<ContestAdminPanel editingContest={null} onSaved={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('contest-template-sprint-1h')).toBeTruthy());
    fireEvent.change(screen.getByTestId('contest-quick-name'), { target: { value: 'My Contest' } });
    fireEvent.click(screen.getByTestId('contest-quick-create'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/contest/from-template', { template_id: 'sprint-1h', name: 'My Contest' }));
    openTab('participants');
    await waitFor(() => expect(screen.getByText(/Create the contest first/)).toBeTruthy());
  });
});
