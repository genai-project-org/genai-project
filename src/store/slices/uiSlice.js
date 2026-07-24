import { createSlice } from '@reduxjs/toolkit';

const storedTheme = (() => {
  try { return localStorage.getItem('iema_theme') || 'dark'; } catch { return 'dark'; }
})();
const storedCollapsed = (() => {
  try { return localStorage.getItem('iema_sidebar') === '1'; } catch { return false; }
})();

const uiSlice = createSlice({
  name: 'ui',
  initialState: {
    theme: storedTheme,  // 'light' | 'dark' | 'system'
    sidebarCollapsed: storedCollapsed,
    walletBalance: null,
  },
  reducers: {
    setTheme: (state, action) => {
      state.theme = action.payload;
      try { localStorage.setItem('iema_theme', action.payload); } catch {}
    },
    toggleSidebar: (state) => {
      state.sidebarCollapsed = !state.sidebarCollapsed;
      try { localStorage.setItem('iema_sidebar', state.sidebarCollapsed ? '1' : '0'); } catch {}
    },
    setSidebar: (state, action) => {
      state.sidebarCollapsed = action.payload;
    },
    setWalletBalance: (state, action) => {
      state.walletBalance = action.payload;
    },
  },
});

export const { setTheme, toggleSidebar, setSidebar, setWalletBalance } = uiSlice.actions;
export default uiSlice.reducer;
