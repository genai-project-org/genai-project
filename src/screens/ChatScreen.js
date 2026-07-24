import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  Alert,
  Image,
  ActivityIndicator,
  Modal,
  FlatList,
} from "react-native";
import { useSelector, useDispatch } from "react-redux";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  ArrowLeft,
  Send,
  Paperclip,
  X,
  Sparkles,
  Loader as LoaderIcon,
  ChevronDown,
  Check,
} from "lucide-react-native";
import * as ImagePicker from "expo-image-picker";
import Markdown from "react-native-markdown-display";
import api, { API_BASE } from "../api";
import { setWalletBalance } from "../store/slices/uiSlice";
import { colors, spacing, fontSize, radii } from "../theme";
import ReportButton from "../components/ReportButton";

export default function ChatScreen({ navigation, route }) {
  const insets = useSafeAreaInsets();
  const { conversationId: initialId, title: initialTitle } = route.params || {};
  const [conversationId, setConversationId] = useState(initialId || null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [meta, setMeta] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState(null);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const scrollRef = useRef(null);
  const { access_token } = useSelector((s) => s.auth);
  const dispatch = useDispatch();

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/chat/models");
        if (data?.items?.length) {
          setModels(data.items);
          const def = data.items.find((m) => m.default) || data.items[0];
          setSelectedModel((cur) => cur ?? def.id);
        }
      } catch {}
    })();
  }, []);

  useEffect(() => {
    if (initialId) {
      (async () => {
        try {
          const { data } = await api.get(`/chat/conversations/${initialId}`);
          setMessages(data.messages);
        } catch {}
      })();
    }
  }, [initialId]);


  useEffect(() => {
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
  }, [messages, streamText]);

  const pickImage = async () => {
    // Uses the Android 13+ system Photo Picker & iOS PHPicker — neither of
    // which requires broad media-library permission. We deliberately do NOT
    // call requestMediaLibraryPermissionsAsync (that requests the deprecated
    // READ_MEDIA_IMAGES permission which Google Play blocks under the photo
    // and video permissions policy).
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.85,
    });
    if (res.canceled) return;
    setUploading(true);
    try {
      const asset = res.assets[0];
      const form = new FormData();
      form.append("file", {
        uri: asset.uri,
        name: asset.fileName || "image.jpg",
        type: asset.mimeType || "image/jpeg",
      });
      const { data } = await api.post("/uploads/image", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setAttachments((a) => [
        ...a,
        {
          url: data.url,
          content_type: data.content_type,
          filename: data.filename,
        },
      ]);
    } catch (err) {
      Alert.alert("Upload failed", err.response?.data?.detail || "Try again");
    } finally {
      setUploading(false);
    }
  };

  const removeAttachment = (idx) =>
    setAttachments((a) => a.filter((_, i) => i !== idx));

  const send = async () => {
    const text = input.trim();
    if ((!text && attachments.length === 0) || streaming) return;
    if (!text) {
      Alert.alert("Add a message", "Please add text along with your image.");
      return;
    }
    const sentAttachments = [...attachments];
    setInput("");
    setAttachments([]);
    setStreaming(true);
    setStreamText("");
    setMeta(null);
    const tmpMsg = {
      id: "u" + Date.now(),
      role: "user",
      content: text,
      attachments: sentAttachments,
    };
    setMessages((m) => [...m, tmpMsg]);

    try {
      // const res = await fetch(`${API_BASE}/chat/stream`, {
      //   method: "POST",
      //   headers: {
      //     "Content-Type": "application/json",
      //     Authorization: `Bearer ${access_token}`,
      //   },
      //   body: JSON.stringify({
      //     content: text,
      //     conversation_id: conversationId,
      //     attachments: sentAttachments,
      //   }),
      // });
      // console.log(res);

      // if (!res.ok) {
      //   const err = await res.json().catch(() => ({}));
      //   throw new Error(err.detail || "Chat failed");
      // }
      // if (!res.body || !res.body.getReader) {
      //   throw new Error("Streaming is not supported on this device.");
      // }

      // const reader = res.body.getReader();
      // const decoder = new TextDecoder();
      // let buffer = "";
      // let finalText = "";
      // let finalMeta = null;

      // while (true) {
      //   const { value, done } = await reader.read();
      //   if (done) break;
      //   buffer += decoder.decode(value, { stream: true });
      //   const events = buffer.split("\n\n");
      //   buffer = events.pop() || "";
      //   for (const evt of events) {
      //     if (!evt.startsWith("data:")) continue;
      //     const payload = evt.replace(/^data:\s*/, "").trim();
      //     if (payload === "[DONE]") continue;
      //     try {
      //       const obj = JSON.parse(payload);
      //       if (obj.type === "conversation") {
      //         if (!conversationId) setConversationId(obj.conversation_id);
      //       } else if (obj.type === "meta") {
      //         finalMeta = obj;
      //         setMeta(obj);
      //       } else if (obj.type === "delta") {
      //         finalText += obj.content;
      //         setStreamText(finalText);
      //       } else if (obj.type === "error") {
      //         Alert.alert("AI error", obj.message);
      //       } else if (obj.type === "saved") {
      //         api
      //           .get("/wallet/")
      //           .then((r) => dispatch(setWalletBalance(r.data.total)));
      //       }
      //     } catch {}
      //   }
      // }
      // if (finalText) {
      //   setMessages((m) => [
      //     ...m,
      //     {
      //       id: "a" + Date.now(),
      //       role: "assistant",
      //       content: finalText,
      //       model: finalMeta?.model,
      //       provider: finalMeta?.provider,
      //     },
      //   ]);
      // }
      // setStreamText("");
      // setMeta(null);

      const { data } = await api.post("/chat", {
        content: text,
        conversation_id: conversationId,
        attachments: sentAttachments,
        model: selectedModel === "iema" ? undefined : selectedModel,
      });

      if (!conversationId) {
        setConversationId(data.conversation_id);
      }

      setMessages((m) => [
        ...m,
        {
          id: "a" + Date.now(),
          role: "assistant",
          content: data.content,
          model: data.model,
          provider: data.provider,
        },
      ]);

      dispatch(setWalletBalance((await api.get("/wallet/")).data.total));
    } catch (e) {
      const detail = e.response?.data?.detail;

      let message = "Something went wrong. Please try again.";

      if (typeof detail === "string") {
        message = detail;
      } else if (detail?.message) {
        message = detail.message;

        if (detail.resets_at) {
          message += `\n\nResets at: ${new Date(
            detail.resets_at
          ).toLocaleString()}`;
        }
      } else if (e.response?.data?.message) {
        message = e.response.data.message;
      } else if (e.message) {
        message = e.message;
      }

      setOut(`⚠️ ${message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={{ flex: 1, backgroundColor: colors.bg }}
    >
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top,
          borderBottomWidth: 1,
          borderColor: colors.border,
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingBottom: 8,
          gap: 12,
        }}
      >
        <TouchableOpacity
          onPress={() => navigation.goBack()}
          style={{ padding: 6 }}
        >
          <ArrowLeft color={colors.text} size={22} />
        </TouchableOpacity>
        <Text
          style={{
            color: colors.text,
            fontSize: fontSize.md,
            fontWeight: "600",
            flex: 1,
          }}
          numberOfLines={1}
        >
          {initialTitle || "New Chat"}
        </Text>
      </View>

      <ScrollView
        ref={scrollRef}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: spacing.md, gap: spacing.lg }}
        keyboardShouldPersistTaps="handled"
      >
        {messages.length === 0 && !streaming && (
          <View style={{ alignItems: "center", paddingTop: 80, gap: 12 }}>
            <View
              style={{
                height: 56,
                width: 56,
                borderRadius: 16,
                backgroundColor: colors.primaryDim,
                borderWidth: 1,
                borderColor: colors.primary,
                alignItems: "center",
                justifyContent: "center",
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
            </View>
            <Text
              style={{
                color: colors.text,
                fontSize: fontSize.xxl,
                fontWeight: "600",
                letterSpacing: -0.5,
              }}
            >
              How can I help you today?
            </Text>
            <Text
              style={{
                color: colors.textMuted,
                textAlign: "center",
                maxWidth: 320,
              }}
            >
              Start a conversation with Claude Haiku 4.5 or GPT-5. Every message
              costs 1 credit, images cost +3 each.
            </Text>
          </View>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {streaming && streamText.length > 0 && (
          <MessageBubble
            message={{
              role: "assistant",
              content: streamText,
              streaming: true,
              model: meta?.model,
            }}
          />
        )}
        {streaming && !streamText && (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <ActivityIndicator size="small" color={colors.primary} />
            <Text style={{ color: colors.textMuted }}>
              {meta ? `Streaming from ${meta.model}...` : "Thinking..."}
            </Text>
          </View>
        )}
      </ScrollView>

      {/* Attachments preview */}
      {attachments.length > 0 && (
        <View
          style={{
            paddingHorizontal: spacing.md,
            paddingTop: 8,
            flexDirection: "row",
            flexWrap: "wrap",
            gap: 6,
          }}
        >
          {attachments.map((att, idx) => (
            <View
              key={idx}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                backgroundColor: colors.card,
                borderWidth: 1,
                borderColor: colors.border,
                borderRadius: radii.md,
                paddingHorizontal: 8,
                paddingVertical: 4,
              }}
            >
              <Text
                style={{
                  color: colors.text,
                  fontSize: fontSize.xs,
                  maxWidth: 120,
                }}
                numberOfLines={1}
              >
                {att.filename}
              </Text>
              <TouchableOpacity onPress={() => removeAttachment(idx)}>
                <X color={colors.textMuted} size={14} />
              </TouchableOpacity>
            </View>
          ))}
        </View>
      )}

      {/* Model picker */}
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingTop: 8,
          flexDirection: "row",
        }}
      >
        <TouchableOpacity
          onPress={() => setModelPickerOpen(true)}
          disabled={streaming}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            paddingHorizontal: 10,
            paddingVertical: 6,
            borderRadius: radii.md,
            borderWidth: 1,
            borderColor: colors.border,
            backgroundColor: colors.card,
          }}
          testID="model-picker-button"
        >
          <Text style={{ color: colors.text, fontSize: fontSize.xs, fontWeight: "600" }}>
            {models.find((m) => m.id === selectedModel)?.name || "Select model"}
          </Text>
          <ChevronDown color={colors.textMuted} size={14} />
        </TouchableOpacity>
      </View>

      <Modal
        visible={modelPickerOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setModelPickerOpen(false)}
      >
        <TouchableOpacity
          style={{ flex: 1, backgroundColor: "#00000080", justifyContent: "flex-end" }}
          activeOpacity={1}
          onPress={() => setModelPickerOpen(false)}
        >
          <View
            style={{
              backgroundColor: colors.card,
              borderTopLeftRadius: radii.lg,
              borderTopRightRadius: radii.lg,
              paddingBottom: Math.max(insets.bottom, spacing.md),
              paddingTop: spacing.md,
            }}
          >
            <Text
              style={{
                color: colors.textMuted,
                fontSize: fontSize.xs,
                fontWeight: "600",
                paddingHorizontal: spacing.md,
                paddingBottom: 8,
              }}
            >
              CHOOSE MODEL
            </Text>
            <FlatList
              data={models}
              keyExtractor={(m) => m.id}
              renderItem={({ item }) => (
                <TouchableOpacity
                  onPress={() => {
                    setSelectedModel(item.id);
                    setModelPickerOpen(false);
                  }}
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "space-between",
                    paddingHorizontal: spacing.md,
                    paddingVertical: 12,
                  }}
                >
                  <View style={{ flex: 1, paddingRight: 12 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Text style={{ color: colors.text, fontSize: fontSize.md, fontWeight: "600" }}>
                        {item.name}
                      </Text>
                      {!!item.label && (
                        <View
                          style={{
                            paddingHorizontal: 6,
                            paddingVertical: 2,
                            borderRadius: radii.sm,
                            backgroundColor: colors.primaryDim,
                          }}
                        >
                          <Text style={{ color: colors.primary, fontSize: 10, fontWeight: "600" }}>
                            {item.label}
                          </Text>
                        </View>
                      )}
                    </View>
                    {!!item.description && (
                      <Text style={{ color: colors.textMuted, fontSize: fontSize.xs, marginTop: 2 }}>
                        {item.description}
                      </Text>
                    )}
                  </View>
                  {selectedModel === item.id && (
                    <Check color={colors.primary} size={18} />
                  )}
                </TouchableOpacity>
              )}
            />
          </View>
        </TouchableOpacity>
      </Modal>

      {/* Input */}
      <View
        style={{
          borderTopWidth: 1,
          borderColor: colors.border,
          padding: spacing.md,
          paddingBottom: Math.max(insets.bottom, spacing.md),
          flexDirection: "row",
          gap: 8,
          alignItems: "flex-end",
        }}
      >
        <TouchableOpacity
          onPress={pickImage}
          disabled={uploading || streaming}
          style={{
            padding: 12,
            borderRadius: radii.md,
            borderWidth: 1,
            borderColor: colors.border,
            backgroundColor: colors.card,
          }}
        >
          {uploading ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : (
            <Paperclip color={colors.textMuted} size={18} />
          )}
        </TouchableOpacity>
        <TextInput
          value={input}
          onChangeText={setInput}
          placeholder="Message IEMA.ai..."
          placeholderTextColor={colors.textDim}
          multiline
          style={{
            flex: 1,
            minHeight: 44,
            maxHeight: 120,
            borderWidth: 1,
            borderColor: colors.border,
            borderRadius: radii.md,
            backgroundColor: colors.card,
            color: colors.text,
            fontSize: fontSize.md,
            paddingHorizontal: 14,
            paddingVertical: 10,
          }}
          testID="chat-input"
        />
        <TouchableOpacity
          onPress={send}
          disabled={(!input.trim() && attachments.length === 0) || streaming}
          style={{
            padding: 12,
            borderRadius: radii.md,
            backgroundColor: colors.primary,
            opacity:
              (!input.trim() && attachments.length === 0) || streaming
                ? 0.5
                : 1,
          }}
          testID="chat-send"
        >
          {streaming ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Send color="#fff" size={18} />
          )}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const mdStyles = {
  body: { color: colors.text, fontSize: fontSize.md, lineHeight: 22 },
  code_inline: {
    backgroundColor: colors.surfaceElevated,
    color: colors.primary,
    fontFamily: colors.mono,
    paddingHorizontal: 4,
    borderRadius: 4,
  },
  code_block: {
    backgroundColor: colors.surfaceElevated,
    color: colors.text,
    padding: 12,
    borderRadius: 8,
    fontFamily: "Menlo",
  },
  fence: {
    backgroundColor: colors.surfaceElevated,
    color: colors.text,
    padding: 12,
    borderRadius: 8,
    fontFamily: "Menlo",
  },
  heading1: {
    color: colors.text,
    fontSize: fontSize.xl,
    fontWeight: "700",
    marginVertical: 8,
  },
  heading2: {
    color: colors.text,
    fontSize: fontSize.lg,
    fontWeight: "600",
    marginVertical: 6,
  },
  heading3: {
    color: colors.text,
    fontSize: fontSize.md,
    fontWeight: "600",
    marginVertical: 4,
  },
  bullet_list_icon: { color: colors.primary },
  link: { color: colors.primary },
  blockquote: {
    backgroundColor: colors.surfaceElevated,
    borderLeftColor: colors.primary,
    borderLeftWidth: 3,
    paddingLeft: 12,
  },
};

function MessageBubble({ message }) {
  const [reported, setReported] = React.useState(false);
  const isUser = message.role === "user";
  return (
    <View
      style={{
        flexDirection: "row",
        gap: 10,
        justifyContent: isUser ? "flex-end" : "flex-start",
      }}
    >
      {!isUser && (
        <View
          style={{
            height: 30,
            width: 30,
            borderRadius: 8,
            backgroundColor: colors.text,
            alignItems: "center",
            justifyContent: "center",
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
        </View>
      )}
      <View
        style={{
          maxWidth: "85%",
          ...(isUser
            ? {
                backgroundColor: colors.primaryDim,
                borderColor: colors.primary + "40",
                borderWidth: 1,
                borderRadius: 14,
                borderTopRightRadius: 4,
                padding: 12,
              }
            : { padding: 4 }),
        }}
      >
        {message.attachments && message.attachments.length > 0 && (
          <View
            style={{
              flexDirection: "row",
              flexWrap: "wrap",
              gap: 6,
              marginBottom: 8,
            }}
          >
            {message.attachments.map((att, idx) => (
              <Image
                key={idx}
                source={{ uri: att.url }}
                style={{
                  width: 140,
                  height: 100,
                  borderRadius: 8,
                  borderWidth: 1,
                  borderColor: colors.border,
                }}
              />
            ))}
          </View>
        )}
        <Markdown style={mdStyles}>{message.content}</Markdown>

        {!isUser && message.model && (
          <>
            <Text
              style={{
                color: colors.textDim,
                fontSize: 10,
                marginTop: 4,
                paddingLeft: 4,
              }}
            >
              {message.model}
            </Text>
            <ReportButton />
          </>
        )}
      </View>
    </View>
  );
}
