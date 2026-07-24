import { createSlice } from '@reduxjs/toolkit';

const uiSlice = createSlice({
  name: 'ui',
  initialState: { walletBalance: null },
  reducers: {
    setWalletBalance: (state, action) => { state.walletBalance = action.payload; },
  },
});
export const { setWalletBalance } = uiSlice.actions;
export default uiSlice.reducer;
