import { createSlice } from '@reduxjs/toolkit';

/**
 * Mock Interview — cross-cutting state only.
 *
 * Everything that's local to a single screen's lifetime (transcript,
 * avatar/animation state, timers, camera/mic readiness) stays as component
 * state in InterviewSessionScreen etc. This slice only holds what needs to
 * survive navigation / be read from multiple screens:
 *  - `entitlement`: shown on the Home screen and used to gate "Start New
 *    Interview" without an extra round trip after a purchase.
 *  - `activeSession`: the session the user is currently mid-flow on (set at
 *    creation, carried through System Check -> Session -> Report so a
 *    backgrounded/killed-and-reopened app can resume mid-session).
 *  - `warningCount`: mirrors the server-authoritative proctoring warning
 *    count so the drawer/home screen can reflect it without re-fetching.
 */
const interviewSlice = createSlice({
  name: 'interview',
  initialState: {
    // { sessions_remaining, grants: [{ grant_id, pack_slug, pack_name,
    //   sessions_total, sessions_remaining, config: {...} }] } — see
    // services/interviewApi.js's getEntitlement doc comment.
    entitlement: null,
    activeSession: null, // { id, topic, phase: 'setup'|'system_check'|'live'|'ended' }
    warningCount: 0,
  },
  reducers: {
    setEntitlement: (state, action) => {
      state.entitlement = action.payload;
    },
    setActiveSession: (state, action) => {
      state.activeSession = action.payload;
    },
    updateActiveSessionPhase: (state, action) => {
      if (state.activeSession) state.activeSession.phase = action.payload;
    },
    clearActiveSession: (state) => {
      state.activeSession = null;
      state.warningCount = 0;
    },
    setWarningCount: (state, action) => {
      state.warningCount = action.payload;
    },
  },
});

export const {
  setEntitlement,
  setActiveSession,
  updateActiveSessionPhase,
  clearActiveSession,
  setWarningCount,
} = interviewSlice.actions;
export default interviewSlice.reducer;
