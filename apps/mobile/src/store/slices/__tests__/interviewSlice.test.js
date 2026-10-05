import reducer, {
  setEntitlement,
  setActiveSession,
  updateActiveSessionPhase,
  clearActiveSession,
  setWarningCount,
} from '../interviewSlice';

describe('interviewSlice', () => {
  const initialState = { entitlement: null, activeSession: null, warningCount: 0 };

  it('returns the initial state', () => {
    expect(reducer(undefined, { type: '@@INIT' })).toEqual(initialState);
  });

  it('stores the entitlement snapshot (aggregate + per-grant config)', () => {
    const entitlement = {
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
    };
    const state = reducer(initialState, setEntitlement(entitlement));
    expect(state.entitlement).toEqual(entitlement);
  });

  it('sets and updates the active session phase', () => {
    let state = reducer(initialState, setActiveSession({ id: 's1', topic: 'hr', phase: 'setup' }));
    expect(state.activeSession).toEqual({ id: 's1', topic: 'hr', phase: 'setup' });

    state = reducer(state, updateActiveSessionPhase('live'));
    expect(state.activeSession.phase).toBe('live');
  });

  it('updateActiveSessionPhase is a no-op when there is no active session', () => {
    const state = reducer(initialState, updateActiveSessionPhase('live'));
    expect(state.activeSession).toBeNull();
  });

  it('tracks the server-reported warning count', () => {
    const state = reducer(initialState, setWarningCount(2));
    expect(state.warningCount).toBe(2);
  });

  it('clearing the active session also resets the warning count', () => {
    let state = reducer(initialState, setActiveSession({ id: 's1', topic: 'hld', phase: 'live' }));
    state = reducer(state, setWarningCount(1));
    state = reducer(state, clearActiveSession());
    expect(state.activeSession).toBeNull();
    expect(state.warningCount).toBe(0);
  });
});
