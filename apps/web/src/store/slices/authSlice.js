import { createSlice } from '@reduxjs/toolkit';

const stored = (() => {
  try {
    const raw = localStorage.getItem('iema_auth');
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
})();

const initialState = {
  user: stored?.user || null,
  access_token: stored?.tokens?.access_token || null,
  refresh_token: stored?.tokens?.refresh_token || null,
};

const persist = (state) => {
  try {
    if (state.access_token) {
      localStorage.setItem('iema_auth', JSON.stringify({
        user: state.user,
        tokens: { access_token: state.access_token, refresh_token: state.refresh_token }
      }));
    } else {
      localStorage.removeItem('iema_auth');
    }
  } catch {}
};

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setAuth: (state, action) => {
      state.user = action.payload.user;
      state.access_token = action.payload.tokens.access_token;
      state.refresh_token = action.payload.tokens.refresh_token;
      persist(state);
    },
    setTokens: (state, action) => {
      state.access_token = action.payload.access_token;
      state.refresh_token = action.payload.refresh_token;
      persist(state);
    },
    setUser: (state, action) => {
      state.user = action.payload;
      persist(state);
    },
    logout: (state) => {
      state.user = null;
      state.access_token = null;
      state.refresh_token = null;
      persist(state);
    },
  },
});

export const { setAuth, setTokens, setUser, logout } = authSlice.actions;
export default authSlice.reducer;
