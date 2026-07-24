import axios from 'axios';
import { store } from '@/store/store';
import { logout, setTokens } from '@/store/slices/authSlice';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = store.getState().auth.access_token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing = null;

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    // FastAPI returns structured detail objects for 429/402 (window/credit limits).
    // Callers do toast.error(data.detail) assuming a string — flatten to avoid
    // "Objects are not valid as a React child".
    const d = error.response?.data?.detail;
    if (d && typeof d === 'object') {
      error.response.data.detail = d.message || 'Request failed';
    }
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      const refresh = store.getState().auth.refresh_token;
      if (!refresh) {
        store.dispatch(logout());
        return Promise.reject(error);
      }
      original._retry = true;
      try {
        if (!refreshing) {
          refreshing = axios.post(`${API_BASE}/auth/refresh`, { refresh_token: refresh });
        }
        const { data } = await refreshing;
        refreshing = null;
        store.dispatch(setTokens(data));
        original.headers.Authorization = `Bearer ${data.access_token}`;
        return api(original);
      } catch (e) {
        refreshing = null;
        store.dispatch(logout());
        return Promise.reject(e);
      }
    }
    return Promise.reject(error);
  }
);

export default api;
