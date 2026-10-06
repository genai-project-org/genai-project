import { createSlice } from '@reduxjs/toolkit';

// Cross-cutting Mock Interview state only — everything else (transcript, avatar
// state, code buffer, timers, wizard step) stays local useState in the page
// components, matching how Practice.jsx/Contest.jsx hold almost everything
// locally. This slice exists so the Sidebar/other pages can show "N sessions
// remaining" or "interview in progress" without re-fetching on every render.
const interviewSlice = createSlice({
  name: 'interview',
  initialState: {
    // `grants` mirrors GET /interview/entitlement's per-pack breakdown — each
    // entry is a distinct purchased/admin-granted pack "format" (its own
    // snapshotted config: durations, allowed topics/seniority/languages/
    // sub-topics) the setup wizard lets the candidate choose between.
    entitlement: { sessionsRemaining: null, sessionsTotal: null, grants: [], packActive: false },
    activeSession: { id: null, phase: null }, // phase: 'created' | 'technical_in_progress' | 'behavioral_in_progress' | null
    warningCount: 0,
  },
  reducers: {
    setEntitlement: (state, action) => {
      const { sessions_remaining, grants } = action.payload || {};
      const g = grants || [];
      state.entitlement = {
        sessionsRemaining: sessions_remaining ?? 0,
        sessionsTotal: g.reduce((sum, x) => sum + (x.sessions_total || 0), 0),
        grants: g,
        packActive: (sessions_remaining ?? 0) > 0,
      };
    },
    setActiveSession: (state, action) => {
      state.activeSession = action.payload;
    },
    clearActiveSession: (state) => {
      state.activeSession = { id: null, phase: null };
      state.warningCount = 0;
    },
    setWarningCount: (state, action) => {
      state.warningCount = action.payload;
    },
  },
});

export const { setEntitlement, setActiveSession, clearActiveSession, setWarningCount } = interviewSlice.actions;
export default interviewSlice.reducer;
