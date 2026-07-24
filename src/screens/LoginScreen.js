import React, { useState } from "react";
import {
  View,
  Text,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
  Alert,
  TouchableOpacity,
  Image,
} from "react-native";
import { useDispatch } from "react-redux";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Sparkles } from "lucide-react-native";
import api from "../api";
import { setAuth } from "../store/slices/authSlice";
import { colors, spacing, fontSize } from "../theme";
import { Button, Input, Label } from "../components/UI";
import SocialAuthButtons from "../components/SocialAuthButtons";

export default function LoginScreen({ navigation }) {
  const insets = useSafeAreaInsets();
  const dispatch = useDispatch();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!email || !password) return;
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      dispatch(setAuth(data));
    } catch (err) {
      Alert.alert(
        "Sign in failed",
        err.response?.data?.detail || "Please try again"
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={{ flex: 1, backgroundColor: colors.bg }}
    >
      <ScrollView
        contentContainerStyle={{
          paddingTop: insets.top + 40,
          paddingHorizontal: spacing.xl,
          paddingBottom: spacing.xl,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            alignSelf: "flex-start",
            marginBottom: 20,
          }}
        >
          <Image
            source={require("../../assets/logo.png")}
            style={{
              width: 36,
              height: 36,
              resizeMode: "contain",
              marginRight: 10,
            }}
          />

          <Text
            style={{
              color: colors.text,
              fontSize: 24,
              fontWeight: "700",
            }}
          >
            IEMA
            <Text style={{ color: colors.primary }}>.</Text>
            ai
          </Text>
        </View>
        <Text
          style={{
            color: colors.text,
            fontSize: fontSize.hero,
            fontWeight: "600",
            letterSpacing: -1,
          }}
        >
          Welcome back
        </Text>
        <Text
          style={{
            color: colors.textMuted,
            fontSize: fontSize.md,
            marginTop: 8,
          }}
        >
          Sign in to continue to your workspace.
        </Text>

        <View style={{ marginTop: 32 }}>
          <SocialAuthButtons />
        </View>

        <View style={{ gap: 12 }}>
          <View>
            <Label>Email</Label>
            <Input
              value={email}
              onChangeText={setEmail}
              placeholder="you@company.com"
              keyboardType="email-address"
              testID="login-email"
            />
          </View>
          <View>
            <View
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <Label>Password</Label>
              <TouchableOpacity
                onPress={() => navigation.navigate("ForgotPassword")}
              >
                <Text
                  style={{ color: colors.textMuted, fontSize: fontSize.xs }}
                >
                  Forgot?
                </Text>
              </TouchableOpacity>
            </View>
            <Input
              value={password}
              onChangeText={setPassword}
              placeholder="••••••••"
              secureTextEntry
              testID="login-password"
            />
          </View>
          <Button
            title="Sign in"
            onPress={submit}
            loading={loading}
            testID="login-submit"
          />
        </View>

        <View style={{ marginTop: 24, alignItems: "center" }}>
          <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
            New here?{" "}
            <Text
              style={{ color: colors.primary, fontWeight: "500" }}
              onPress={() => navigation.navigate("Register")}
            >
              Create an account
            </Text>
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
