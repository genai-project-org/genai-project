import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Platform,
  Alert,
} from "react-native";
import * as AuthSession from "expo-auth-session";
import * as WebBrowser from "expo-web-browser";
import * as AppleAuthentication from "expo-apple-authentication";
import { useDispatch } from "react-redux";
import api from "../api";
import { setAuth } from "../store/slices/authSlice";
import { colors, spacing, radii, fontSize } from "../theme";

WebBrowser.maybeCompleteAuthSession();

const GOOGLE_DISCOVERY = {
  authorizationEndpoint: "https://accounts.google.com/o/oauth2/v2/auth",
  tokenEndpoint: "https://oauth2.googleapis.com/token",
};
const GITHUB_DISCOVERY = {
  authorizationEndpoint: "https://github.com/login/oauth/authorize",
  tokenEndpoint: "https://github.com/login/oauth/access_token",
};
const LINKEDIN_DISCOVERY = {
  authorizationEndpoint: "https://www.linkedin.com/oauth/v2/authorization",
  tokenEndpoint: "https://www.linkedin.com/oauth/v2/accessToken",
};

/**
 * Mobile social sign-in. Google, GitHub and LinkedIn all use the plain
 * OAuth 2.0 code flow — we forward the `code` to the same backend endpoints
 * used by the web app (`/api/auth/{google-verify|github|linkedin}`), which
 * already know how to complete the exchange. Apple stays on the native
 * StoreKit flow via `expo-apple-authentication` (App Store required on iOS).
 *
 * Microsoft and Facebook are intentionally excluded — Microsoft's flow has
 * not been stabilised behind our reverse proxy and Facebook is not
 * whitelisted in Meta for Developers.
 */
export default function SocialAuthButtons() {
  const dispatch = useDispatch();
  const [loading, setLoading] = useState(null);
  const [oauthCfg, setOauthCfg] = useState({
    google: {},
    apple: {},
    github: {},
    linkedin: {},
  });

  useEffect(() => {
    const loadOAuthConfig = async () => {
      try {
        console.log("Fetching OAuth config...");

        const res = await api.get("/auth/oauth-config");

        console.log("OAuth Config:", JSON.stringify(res.data, null, 2));

        setOauthCfg(res.data);
      } catch (err) {
        console.log("OAuth Config Error");
        console.log("Message:", err.message);
        console.log("Status:", err.response?.status);
        console.log("Data:", err.response?.data);
        console.log("URL:", err.config?.baseURL + err.config?.url);
        console.log(err);
      }
    };

    loadOAuthConfig();
  }, []);

  const redirectUri = AuthSession.makeRedirectUri({
    scheme: "iemaai",
    path: "auth",
  });
  const finish = (data) => {
    dispatch(setAuth(data));
  };

  const withProvider = async (provider, run) => {
    if (loading) return;
    setLoading(provider);
    try {
      await run();
    } catch (e) {
      if (e?.code === "ERR_CANCELED" || e?.type === "cancel") return;
      Alert.alert(
        `${provider} sign-in failed`,
        e?.response?.data?.detail || e?.message || "Try again"
      );
    } finally {
      setLoading(null);
    }
  };

  // Google, GitHub and LinkedIn all go through the web bridge — none of
  // them register the custom scheme `iemaai://auth`, only the already-
  // deployed web `/auth/callback` URL. The bridge does the OAuth dance
  // there, then hands JWTs back to the app via `iemaai://auth?…`.
  const signInGoogle = () =>
    withProvider("google", async () => {
      if (!oauthCfg.google?.enabled) throw new Error("Google not configured");
      const data = await webBridge("google");
      if (data) finish(data);
    });

  // Same callback URL as the web app (`/auth/callback`) — it's the ONLY
  // redirect URI each OAuth provider has registered, and it's the one
  // GitHub requires ("must be exactly one" per app). The web callback page
  // detects `state=mobile:*` and finishes by 302-ing back to `iemaai://auth`.
  const webBridge = async (provider) => {
    const { data: cfg } = await api.get("/auth/oauth-config");
    if (!cfg?.[provider]?.enabled)
      throw new Error(`${provider} not configured`);
    const webOrigin = String(api.defaults.baseURL || "").replace(
      /\/api\/?$/,
      ""
    );
    if (!webOrigin) throw new Error("API base URL missing");
    const webCallback = `${webOrigin}/auth/callback`;
    const state = `mobile:${provider}:iemaai:${Math.random()
      .toString(36)
      .slice(2, 10)}`;

    let authUrl;
    if (provider === "github") {
      authUrl =
        "https://github.com/login/oauth/authorize?" +
        new URLSearchParams({
          client_id: cfg.github.client_id,
          redirect_uri: webCallback,
          scope: "read:user user:email",
          state,
        }).toString();
    } else if (provider === "linkedin") {
      authUrl =
        "https://www.linkedin.com/oauth/v2/authorization?" +
        new URLSearchParams({
          response_type: "code",
          client_id: cfg.linkedin.client_id,
          redirect_uri: webCallback,
          scope: "openid profile email",
          state,
        }).toString();
    } else if (provider === "google") {
      authUrl =
        "https://accounts.google.com/o/oauth2/v2/auth?" +
        new URLSearchParams({
          client_id: cfg.google.client_id,
          redirect_uri: webCallback,
          response_type: "code",
          scope: "openid email profile",
          state,
          prompt: "select_account",
        }).toString();
    } else if (provider === "apple") {
      authUrl =
        "https://appleid.apple.com/auth/authorize?" +
        new URLSearchParams({
          client_id: cfg.apple.client_id,
          redirect_uri: webCallback,
          response_type: "code",
          response_mode: "form_post",
          scope: "name email",
          state,
        }).toString();
    } else {
      throw new Error(`Unsupported provider: ${provider}`);
    }
    console.log("================================");
    console.log("Provider:", provider);
    console.log("Web Origin:", webOrigin);
    console.log("Callback:", webCallback);
    console.log("Auth URL:", authUrl);
    console.log("Return URL:", "iemaai://auth");
    console.log("================================");
    const res = await WebBrowser.openAuthSessionAsync(authUrl, "iemaai://auth");
    if (res.type !== "success" || !res.url) return null;
    // Returning URL is `iemaai://auth?access_token=…&refresh_token=…&user=…`
    const q = res.url.split("?")[1] || "";
    const params = Object.fromEntries(new URLSearchParams(q).entries());
    if (params.error) throw new Error(params.error);
    if (!params.access_token) throw new Error("No token returned");
    return {
      user: params.user ? JSON.parse(params.user) : null,
      tokens: {
        access_token: params.access_token,
        refresh_token: params.refresh_token,
      },
    };
  };

  const signInGithub = () =>
    withProvider("github", async () => {
      if (!oauthCfg.github?.enabled) throw new Error("GitHub not configured");
      const data = await webBridge("github");
      if (data) finish(data);
    });

  const signInLinkedIn = () =>
    withProvider("linkedin", async () => {
      if (!oauthCfg.linkedin?.enabled)
        throw new Error("LinkedIn not configured");
      const data = await webBridge("linkedin");
      if (data) finish(data);
    });

  const signInApple = () =>
    withProvider("apple", async () => {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      const idToken = credential.identityToken;
      if (!idToken) throw new Error("No identity token from Apple");
      const { data } = await api.post("/auth/apple", { id_token: idToken });
      finish(data);
    });

  const chip = (label, onPress, key, testID, disabled) => (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      disabled={disabled || loading !== null}
      activeOpacity={0.85}
      style={{
        flex: 1,
        height: 44,
        borderRadius: radii.md,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: "center",
        justifyContent: "center",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {loading === key ? (
        <ActivityIndicator size="small" color={colors.text} />
      ) : (
        <Text
          style={{
            color: colors.text,
            fontSize: fontSize.sm,
            fontWeight: "500",
          }}
        >
          {label}
        </Text>
      )}
    </TouchableOpacity>
  );

  return (
    <View style={{ gap: spacing.sm }}>
      <TouchableOpacity
        testID="social-google"
        onPress={signInGoogle}
        disabled={loading !== null || !oauthCfg.google?.enabled}
        activeOpacity={0.85}
        style={{
          height: 46,
          borderRadius: radii.md,
          borderWidth: 1,
          borderColor: colors.border,
          backgroundColor: colors.surface,
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          opacity: oauthCfg.google?.enabled ? 1 : 0.5,
        }}
      >
        {loading === "google" ? (
          <ActivityIndicator size="small" color={colors.text} />
        ) : (
          <Text
            style={{
              color: colors.text,
              fontSize: fontSize.md,
              fontWeight: "500",
            }}
          >
            Continue with Google
          </Text>
        )}
      </TouchableOpacity>
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        {chip(
          "Apple",
          () => webBridge("apple").then((d) => d && finish(d)),
          "apple",
          "social-apple",
          !oauthCfg.apple?.enabled
        )}
        {chip(
          "GitHub",
          signInGithub,
          "github",
          "social-github",
          !oauthCfg.github?.enabled
        )}
        {chip(
          "LinkedIn",
          signInLinkedIn,
          "linkedin",
          "social-linkedin",
          !oauthCfg.linkedin?.enabled
        )}
      </View>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          marginVertical: spacing.md,
        }}
      >
        <View style={{ flex: 1, height: 1, backgroundColor: colors.border }} />
        <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>
          or continue with email
        </Text>
        <View style={{ flex: 1, height: 1, backgroundColor: colors.border }} />
      </View>
    </View>
  );
}
