import axios from "axios";
import Constants from "expo-constants";
import { store } from "./store/store";
import { logout, setTokens } from "./store/slices/authSlice";

const apiBase = Constants.expoConfig?.extra?.apiBaseUrl;

if (!apiBase) {
  throw new Error("apiBaseUrl missing from app.json");
}

const API_BASE = `${apiBase}/api`;

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
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      const refresh = store.getState().auth.refresh_token;
      if (!refresh) {
        store.dispatch(logout());
        return Promise.reject(error);
      }
      original._retry = true;
      try {
        if (!refreshing)
          refreshing = axios.post(`${API_BASE}/auth/refresh`, {
            refresh_token: refresh,
          });
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

export { API_BASE };
export default api;
