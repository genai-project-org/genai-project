import axios from "axios";
import { Alert } from "react-native";
import { navigationRef } from "./navigationRef";
import Constants from "expo-constants";
import { store } from "./store/store";
import { logout, setTokens } from "./store/slices/authSlice";

const apiBase = Constants.expoConfig?.extra?.apiBaseUrl;

if (!apiBase) {
  throw new Error("apiBaseUrl missing from app.config.js");
}

const API_BASE = `${apiBase}/api`;

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = store.getState().auth.access_token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing = null;
let rechargePromptOpen = false;
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    // Out of credits is a prompt, not an error wall.
    if (error.response?.status === 402 && !rechargePromptOpen) {
      rechargePromptOpen = true;
      Alert.alert(
        "Time for a quick recharge",
        "You need a few more credits for that. Add credits any time; they never expire.",
        [
          { text: "Not now", style: "cancel", onPress: () => { rechargePromptOpen = false; } },
          {
            text: "Recharge",
            onPress: () => {
              rechargePromptOpen = false;
              if (navigationRef.isReady()) navigationRef.navigate("Billing");
            },
          },
        ],
        { onDismiss: () => { rechargePromptOpen = false; } },
      );
    }
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
