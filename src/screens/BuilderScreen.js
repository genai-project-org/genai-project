import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  Linking,
  Modal,
  RefreshControl,
} from "react-native";
import {
  Code2,
  Plus,
  Share2,
  RefreshCcw,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react-native";
import api from "../api";
import ScreenHeader from "../components/ScreenHeader";
import { Card, Button, Input, Label } from "../components/UI";
import { colors, spacing, fontSize, radii } from "../theme";
import ReportButton from "../components/ReportButton";
import { BackHandler } from "react-native";
import { useFocusEffect } from "@react-navigation/native";

export default function BuilderScreen({ navigation }) {
  const [projects, setProjects] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [active, setActive] = useState(null);
  const [refineText, setRefineText] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useFocusEffect(
    React.useCallback(() => {
      const onBackPress = () => {
        if (active) {
          setActive(null);
          return true; // We handled the back press.
        }

        return false; // Let React Navigation go back normally.
      };

      const subscription = BackHandler.addEventListener(
        "hardwareBackPress",
        onBackPress
      );

      return () => subscription.remove();
    }, [active])
  );

  const getApiError = (e, fallback = "Something went wrong.") => {
    const detail = e.response?.data?.detail;

    if (typeof detail === "string") return detail;

    if (detail?.message) {
      return detail.resets_at
        ? `${detail.message}\n\nResets at: ${new Date(
            detail.resets_at
          ).toLocaleString()}`
        : detail.message;
    }

    return e.response?.data?.message || e.message || fallback;
  };

  const load = async () => {
    setRefreshing(true);

    try {
      const { data } = await api.get("/builder/projects");
      setProjects(data.items || []);
    } catch (e) {
      alert(getApiError(e, "Failed to load projects."));
    } finally {
      setRefreshing(false);
    }
  };
  useEffect(() => {
    load();
  }, []);

  const openProject = async (id) => {
    setBusy(true);

    try {
      const { data } = await api.get(`/builder/projects/${id}`);
      setActive(data);
    } catch (e) {
      alert(getApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const share = async () => {
    if (!active) return;

    setBusy(true);

    try {
      const { data } = await api.post(`/builder/projects/${active.id}/share`);

      if (data.share_url) {
        Linking.openURL(data.share_url);
      }
    } catch (e) {
      alert(getApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const refine = async () => {
    if (!active || !refineText.trim()) return;

    setBusy(true);

    try {
      const { data } = await api.post(`/builder/projects/${active.id}/refine`, {
        instruction: refineText,
      });

      setActive((prev) => ({
        ...prev,
        files: data.files,
        updated_at: new Date().toISOString(),
      }));

      setRefineText("");

      load();
    } catch (e) {
      alert(getApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const del = async (id) => {
    try {
      await api.delete(`/builder/projects/${id}`);

      setProjects((prev) => prev.filter((x) => x.id !== id));

      if (active?.id === id) {
        setActive(null);
      }

      load();
    } catch (e) {
      alert(getApiError(e));
    }
  };

  if (active) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        <ScreenHeader
          title={active.name}
          navigation={navigation}
          onBack={() => setActive(null)}
        />
        <ScrollView
          contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
        >
          <Card>
            <Text
              style={{
                color: colors.primary,
                fontSize: fontSize.sm,
                fontWeight: "600",
              }}
            >
              {active.files?.length ?? 0} generated files
            </Text>

            <Text
              style={{
                color: colors.textDim,
                marginTop: 4,
              }}
            >
              Ready for refinement
            </Text>
            <Text
              style={{
                color: colors.text,
                fontSize: fontSize.md,
                marginTop: 6,
              }}
            >
              {active.description}
            </Text>
            <Button
              title="Open Preview (share URL)"
              onPress={share}
              loading={busy}
              style={{ marginTop: spacing.md }}
              testID="builder-mobile-share-btn"
            />
          </Card>
          <Card>
            <Label>Refine with AI (8 credits)</Label>
            <Input
              value={refineText}
              onChangeText={setRefineText}
              placeholder="e.g. Add dark mode toggle"
              testID="builder-mobile-refine-input"
            />
            <Button
              title="Refine"
              onPress={refine}
              loading={busy}
              disabled={!refineText.trim()}
              style={{ marginTop: spacing.sm }}
              testID="builder-mobile-refine-btn"
            />
          </Card>
          {active.files?.length === 0 ? (
            <Card>
              <Text
                style={{
                  color: colors.textDim,
                  textAlign: "center",
                }}
              >
                ✨ Preparing your project...
              </Text>

              <Text
                style={{
                  color: colors.textDim,
                  textAlign: "center",
                  marginTop: 8,
                }}
              >
                Generated files will appear shortly.
              </Text>
            </Card>
          ) : (
            active.files.map((f, i) => (
              <Card key={i}>
                <Text
                  style={{
                    color: colors.primary,
                    fontSize: fontSize.sm,
                    fontWeight: "500",
                  }}
                >
                  {f.path}
                </Text>
                <Text
                  style={{
                    color: colors.textDim,
                    fontSize: fontSize.xs,
                    fontFamily: "Menlo",
                    marginTop: 6,
                    lineHeight: 16,
                  }}
                  numberOfLines={20}
                >
                  {f.content}
                </Text>
              </Card>
            ))
          )}
          <Card>
            <ReportButton />
          </Card>
        </ScrollView>
      </View>
    );
  }

  return (
    <View
      style={{ flex: 1, backgroundColor: colors.bg }}
      testID="builder-screen"
    >
      <ScreenHeader title="Code Builder" navigation={navigation} />
      <ScrollView
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={load}
            tintColor={colors.primary}
          />
        }
        contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
      >
        <Button
          title="+ New Project"
          onPress={() => setShowCreate(true)}
          testID="builder-mobile-new-btn"
        />
        {projects.length === 0 && (
          <Card>
            <Text
              style={{
                color: colors.textDim,
                fontSize: fontSize.sm,
                textAlign: "center",
              }}
            >
              ✨ No projects yet. Create your first AI-generated application.
              Your generated projects will always stay here, just like ChatGPT
              conversations.
            </Text>
          </Card>
        )}
        {projects.map((p) => (
          <Card key={p.id} style={{ marginBottom: spacing.md }}>
            <TouchableOpacity onPress={() => openProject(p.id)}>
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                }}
              >
                <Code2 color={colors.primary} size={18} />

                <View style={{ flex: 1, marginLeft: 10 }}>
                  <Text
                    style={{
                      color: colors.text,
                      fontSize: fontSize.md,
                      fontWeight: "600",
                    }}
                    numberOfLines={1}
                  >
                    {p.name}
                  </Text>

                  <Text
                    style={{
                      color: colors.textDim,
                      fontSize: fontSize.xs,
                      marginTop: 3,
                    }}
                    numberOfLines={2}
                  >
                    {p.description}
                  </Text>

                  <Text
                    style={{
                      color: colors.primary,
                      fontSize: fontSize.xs,
                      marginTop: 8,
                    }}
                  >
                    {p.file_count ?? 0} file(s)
                  </Text>
                </View>

                <TouchableOpacity onPress={() => del(p.id)}>
                  <Trash2 color={colors.textDim} size={16} />
                </TouchableOpacity>
              </View>
            </TouchableOpacity>
          </Card>
        ))}
      </ScrollView>
      <CreateModal
        visible={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(project) => {
          setProjects((prev) => [project, ...prev]);

          setShowCreate(false);

          openProject(project.id);

          setTimeout(load, 400);
        }}
      />
    </View>
  );
}

function CreateModal({ visible, onClose, onCreated }) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (prompt.trim().length < 8) return;
    setBusy(true);
    try {
      const { data } = await api.post("/builder/projects", { prompt });
      onCreated(data.project);
      setPrompt("");
    } catch (e) {
      const detail = e.response?.data?.detail;

      let message = "Failed to load projects.";

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
      }

      alert(message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <View
        style={{
          flex: 1,
          justifyContent: "flex-end",
          backgroundColor: "rgba(0,0,0,0.6)",
        }}
      >
        <View
          style={{
            backgroundColor: colors.surface,
            padding: spacing.lg,
            borderTopLeftRadius: 20,
            borderTopRightRadius: 20,
            gap: 10,
          }}
        >
          <Text
            style={{
              color: colors.text,
              fontSize: fontSize.lg,
              fontWeight: "600",
            }}
          >
            New Project
          </Text>
          <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>
            15 credits per project. Cache hits are free.
          </Text>
          <Input
            value={prompt}
            onChangeText={setPrompt}
            multiline
            placeholder="Describe what to build..."
            style={{ minHeight: 120, textAlignVertical: "top", paddingTop: 10 }}
            testID="builder-mobile-create-prompt"
          />
          <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
            <Button
              title="Cancel"
              onPress={onClose}
              variant="outline"
              style={{ flex: 1 }}
            />
            <Button
              title="Generate"
              onPress={submit}
              loading={busy}
              disabled={prompt.trim().length < 8}
              style={{ flex: 1 }}
              testID="builder-mobile-create-submit"
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}
