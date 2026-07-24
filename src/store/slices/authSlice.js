import { createSlice } from '@reduxjs/toolkit';
import { persistAuth } from '../../authStorage';

const authSlice = createSlice({
  name: 'auth',
  initialState: { user: null, access_token: null, refresh_token: null, hydrated: false },
  reducers: {
    setAuth: (state, action) => {
      state.user = action.payload.user;
      state.access_token = action.payload.tokens.access_token;
      state.refresh_token = action.payload.tokens.refresh_token;
      persistAuth(state);
    },
    setTokens: (state, action) => {
      state.access_token = action.payload.access_token;
      state.refresh_token = action.payload.refresh_token;
      persistAuth(state);
    },
    setUser: (state, action) => { state.user = action.payload; persistAuth(state); },
    hydrate: (state, action) => {
      if (action.payload) {
        state.user = action.payload.user;
        state.access_token = action.payload.tokens?.access_token || null;
        state.refresh_token = action.payload.tokens?.refresh_token || null;
      }
      state.hydrated = true;
    },
    logout: (state) => {
      state.user = null;
      state.access_token = null;
      state.refresh_token = null;
      persistAuth(state);
    },
  },
});

export const { setAuth, setTokens, setUser, hydrate, logout } = authSlice.actions;
export default authSlice.reducer;
