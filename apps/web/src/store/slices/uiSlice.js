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
    rechargePrompt: null, // { balance, needed } when an action was blocked by an empty wallet
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
    showRecharge: (state, action) => {
      state.rechargePrompt = action.payload || {};
    },
    hideRecharge: (state) => {
      state.rechargePrompt = null;
    },
  },
});

export const { setTheme, toggleSidebar, setSidebar, setWalletBalance, showRecharge, hideRecharge } = uiSlice.actions;
export default uiSlice.reducer;
