import { configureStore } from '@reduxjs/toolkit';
import authReducer from './slices/authSlice';
import uiReducer from './slices/uiSlice';
import interviewReducer from './slices/interviewSlice';

export const store = configureStore({
  reducer: {
    auth: authReducer,
    ui: uiReducer,
    interview: interviewReducer,
  },
});
