import * as SecureStore from "expo-secure-store";

// Split out from api.js so authSlice.js doesn't need to import api.js, which
// itself imports store.js (which imports authSlice.js) — that three-way
// cycle was causing transient "useDispatch doesn't exist" crashes under
// Metro/Fast Refresh.
export const persistAuth = async (state) => {
  try {
    if (state.access_token) {
      await SecureStore.setItemAsync(
        "iema_auth",
        JSON.stringify({
          user: state.user,
          tokens: {
            access_token: state.access_token,
            refresh_token: state.refresh_token,
          },
        })
      );
    } else {
      await SecureStore.deleteItemAsync("iema_auth");
    }
  } catch {}
};

export const loadAuth = async () => {
  try {
    const raw = await SecureStore.getItemAsync("iema_auth");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};
