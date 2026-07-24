import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  TextInput,
} from "react-native";
import {
  Heart,
  Briefcase,
  GraduationCap,
  Send,
  Database,
  Sparkles,
} from "lucide-react-native";
import api from "../api";
import ScreenHeader from "../components/ScreenHeader";
import ReportButton from "../components/ReportButton";
import { colors, spacing, fontSize, radii } from "../theme";

const MODES = [
  { key: "career", label: "Career", Icon: Briefcase },
  { key: "psychology", label: "Wellness", Icon: Heart },
  { key: "academic", label: "Academic", Icon: GraduationCap },
];

export default function CounselingScreen({ navigation }) {
  const [mode, setMode] = useState("career");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    setMessages([]);
  }, [mode]);
  useEffect(() => {
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
  }, [messages, loading]);

  const send = async () => {
    const text = input.trim();
    if (text.length < 3) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setLoading(true);
    try {
      const { data } = await api.post("/counseling", { mode, message: text });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: data.response,
          source: data.source,
          score: data.score,
          disclaimer: data.disclaimer,
          credits: data.credits_used,
        },
      ]);
    } catch (e) {
      const message =
        e.response?.data?.detail ||
        e.response?.data?.message ||
        e.message ||
        "Something went wrong.";

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `⚠️ Your usage window has exhausted, please for sometime, or top-up to continue`,
          source: "error",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: colors.bg }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      testID="counseling-screen"
    >
      <ScreenHeader title="Counseling" navigation={navigation} />
      <View
        style={{
          flexDirection: "row",
          paddingHorizontal: spacing.md,
          paddingTop: spacing.md,
          gap: 6,
        }}
      >
        {MODES.map((m) => (
          <TouchableOpacity
            key={m.key}
            onPress={() => setMode(m.key)}
            testID={`counseling-mode-${m.key}`}
            style={{
              flex: 1,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: 4,
              paddingVertical: 10,
              borderRadius: radii.md,
              borderWidth: 1,
              borderColor: mode === m.key ? colors.primary : colors.border,
              backgroundColor:
                mode === m.key ? colors.primaryDim : "transparent",
            }}
          >
            <m.Icon
              color={mode === m.key ? colors.primary : colors.textMuted}
              size={13}
            />
            <Text
              style={{
                color: mode === m.key ? colors.primary : colors.textMuted,
                fontSize: fontSize.sm,
                fontWeight: "500",
              }}
            >
              {m.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.sm,
          paddingBottom: 40,
        }}
      >
        {messages.length === 0 && (
          <View
            style={{
              backgroundColor: colors.surface,
              borderRadius: radii.lg,
              borderWidth: 1,
              borderColor: colors.border,
              padding: spacing.lg,
              alignItems: "center",
            }}
          >
            <Heart color={colors.primary} size={24} />
            <Text
              style={{
                color: colors.text,
                fontSize: fontSize.md,
                marginTop: 8,
                fontWeight: "500",
              }}
            >
              Start a private conversation
            </Text>
            <Text
              style={{
                color: colors.textDim,
                fontSize: fontSize.xs,
                marginTop: 4,
                textAlign: "center",
              }}
            >
              Data lake first. Fresh AI answers = 3 credits.
            </Text>
          </View>
        )}
        {messages.map((m, i) => (
          <View
            key={i}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "85%",
              backgroundColor:
                m.role === "user" ? colors.primary : colors.surface,
              borderRadius: radii.lg,
              borderWidth: m.role === "user" ? 0 : 1,
              borderColor: colors.border,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
            }}
          >
            <Text
              style={{
                color: m.role === "user" ? "white" : colors.text,
                fontSize: fontSize.sm,
                lineHeight: 20,
              }}
            >
              {m.text}
            </Text>
            {m.role === "assistant" && (
              <>
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 4,
                    marginTop: 8,
                  }}
                >
                  {m.source === "kb" ? (
                    <>
                      <Database color="#10b981" size={10} />
                      <Text style={{ color: "#10b981", fontSize: 10 }}>
                        Data Lake · 0 credits
                      </Text>
                    </>
                  ) : (
                    <>
                      <Sparkles color={colors.primary} size={10} />
                      <Text style={{ color: colors.primary, fontSize: 10 }}>
                        Fresh AI · {m.credits} credits
                      </Text>
                    </>
                  )}
                </View>

                <ReportButton />
              </>
            )}
            {m.disclaimer && (
              <Text
                style={{
                  color: colors.textDim,
                  fontSize: 10,
                  marginTop: 6,
                  fontStyle: "italic",
                }}
              >
                {m.disclaimer}
              </Text>
            )}
          </View>
        ))}
        {loading && (
          <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>
            Consulting…
          </Text>
        )}
      </ScrollView>
      <View
        style={{
          padding: spacing.sm,
          borderTopWidth: 1,
          borderColor: colors.border,
          backgroundColor: colors.bg,
          flexDirection: "row",
          gap: 6,
        }}
      >
        <TextInput
          value={input}
          onChangeText={setInput}
          placeholder="Ask anything…"
          placeholderTextColor={colors.textDim}
          multiline
          style={{
            flex: 1,
            backgroundColor: colors.surface,
            borderColor: colors.border,
            borderWidth: 1,
            borderRadius: radii.md,
            color: colors.text,
            paddingHorizontal: 12,
            paddingVertical: 10,
            maxHeight: 100,
          }}
          testID="counseling-input"
        />
        <TouchableOpacity
          onPress={send}
          disabled={loading || input.trim().length < 3}
          style={{
            backgroundColor: colors.primary,
            opacity: input.trim().length < 3 ? 0.5 : 1,
            borderRadius: radii.md,
            paddingHorizontal: 14,
            alignItems: "center",
            justifyContent: "center",
          }}
          testID="counseling-send-btn"
        >
          <Send color="white" size={16} />
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}
