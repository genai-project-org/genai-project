import React, { useEffect, useMemo, useState } from "react";
import { View, Text, ScrollView, TouchableOpacity, ActivityIndicator } from "react-native";
import {
  Trophy, Users, Clock, CheckCircle2, UserPlus, Search, User as UserIcon, Plus,
} from "lucide-react-native";
import api from "../api";
import ScreenHeader from "../components/ScreenHeader";
import { Card, Button, Input, Label, Divider } from "../components/UI";
import { colors, spacing, fontSize, radii } from "../theme";

// Same flattening trick the web app's Contest.jsx uses — FastAPI's 4xx
// responses carry structured `detail` objects sometimes, a plain string
// other times.
function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(", ");
  if (d && typeof d === "object") return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

const ACCENT_COLORS = {
  indigo: "#6366f1", violet: "#8b5cf6", emerald: "#10b981",
  amber: "#f59e0b", rose: "#f43f5e", sky: "#0ea5e9",
};

/**
 * Mobile's ONLY contest-related screen — registration for a contest's team,
 * nothing else. Deliberately no code editor, no problem list, no submission
 * flow: solving/submitting contest problems is web-only (Practice Engine's
 * real code editor lives there). This mirrors the structured landing-page
 * content the web app renders (services/contest_service.py's
 * generate_landing_page output — a headline/tagline/highlights/accent, never
 * raw HTML), just laid out natively instead of pixel-matching the web page.
 */
export default function ContestScreen({ navigation }) {
  const [contests, setContests] = useState([]);
  const [contestId, setContestId] = useState(null);
  const [contest, setContest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [mode, setMode] = useState("create"); // 'create' | 'join' | 'solo'
  const [teamName, setTeamName] = useState("");
  const [teammateEmails, setTeammateEmails] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [openTeams, setOpenTeams] = useState(null);
  const [loadingOpenTeams, setLoadingOpenTeams] = useState(false);
  const [joiningId, setJoiningId] = useState(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError("");
      try {
        const { data } = await api.get("/contest/");
        const items = data.items || [];
        setContests(items);
        if (items.length) {
          const live = items.find((c) => c.status === "live");
          setContestId((live || items[0]).id);
        } else {
          setLoading(false);
        }
      } catch (e) {
        setError(detailToString(e, "Failed to load contests"));
        setLoading(false);
      }
    })();
  }, []);

  const loadContest = async (id) => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get(`/contest/${id}`);
      setContest(data);
    } catch (e) {
      setError(detailToString(e, "Failed to load contest"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (contestId) loadContest(contestId);
  }, [contestId]);

  useEffect(() => {
    if (mode !== "join" || !contestId || contest?.my_team) return;
    (async () => {
      setLoadingOpenTeams(true);
      try {
        const { data } = await api.get(`/contest/${contestId}/teams/open`);
        setOpenTeams(data.items || []);
      } catch (e) {
        setOpenTeams([]);
      } finally {
        setLoadingOpenTeams(false);
      }
    })();
  }, [mode, contestId, contest?.my_team]);

  const copy = useMemo(() => {
    if (!contest) return null;
    return contest.landing_page || {
      headline: `Register for ${contest.name}`,
      tagline: "A free, team-based coding contest.",
      highlights: ["Free entry", "Team-based", "Live leaderboard"],
      accent: "indigo",
    };
  }, [contest]);
  const accentColor = ACCENT_COLORS[copy?.accent] || colors.primary;

  const createTeam = async (openToJoin) => {
    if (!teamName.trim() || submitting) return;
    setSubmitting(true);
    try {
      const member_emails = teammateEmails.split(",").map((e) => e.trim()).filter(Boolean);
      await api.post(`/contest/${contestId}/teams`, {
        name: teamName.trim(), member_emails, open_to_join: openToJoin,
      });
      setTeamName("");
      setTeammateEmails("");
      await loadContest(contestId);
    } catch (e) {
      setError(detailToString(e, "Failed to register team"));
    } finally {
      setSubmitting(false);
    }
  };

  const registerSolo = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await api.post(`/contest/${contestId}/teams`, {
        name: "Solo Team", member_emails: [], open_to_join: false,
      });
      await loadContest(contestId);
    } catch (e) {
      setError(detailToString(e, "Failed to register"));
    } finally {
      setSubmitting(false);
    }
  };

  const joinOpenTeam = async (teamId) => {
    if (joiningId) return;
    setJoiningId(teamId);
    try {
      await api.post(`/contest/${contestId}/teams/${teamId}/join`);
      await loadContest(contestId);
    } catch (e) {
      setError(detailToString(e, "Failed to join team"));
    } finally {
      setJoiningId(null);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }} testID="contest-screen">
      <ScreenHeader title="Contest" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        {loading && (
          <View style={{ paddingVertical: 40, alignItems: "center" }}>
            <ActivityIndicator color={colors.primary} />
          </View>
        )}

        {!loading && contests.length === 0 && !error && (
          <Card>
            <Text style={{ color: colors.textMuted, textAlign: "center" }}>
              No contests are running right now. Check back soon.
            </Text>
          </Card>
        )}

        {error ? (
          <Card style={{ borderColor: colors.destructive }}>
            <Text style={{ color: colors.destructive, fontSize: fontSize.sm }}>{error}</Text>
          </Card>
        ) : null}

        {!loading && contest && (
          <>
            {/* Contest picker, if more than one */}
            {contests.length > 1 && (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: -spacing.sm }}>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  {contests.map((c) => (
                    <TouchableOpacity
                      key={c.id}
                      onPress={() => setContestId(c.id)}
                      style={{
                        paddingHorizontal: 12, paddingVertical: 8, borderRadius: radii.full,
                        borderWidth: 1, borderColor: c.id === contestId ? colors.primary : colors.border,
                        backgroundColor: c.id === contestId ? colors.primaryDim : "transparent",
                      }}
                    >
                      <Text style={{ color: c.id === contestId ? colors.primary : colors.textMuted, fontSize: fontSize.sm }}>
                        {c.name}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </ScrollView>
            )}

            {/* Structured landing content — native layout of the same
                LLM-generated (or fallback) copy the web landing page uses. */}
            <Card style={{ borderColor: accentColor + "50" }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 }}>
                <Trophy size={16} color={accentColor} />
                <Text style={{ color: accentColor, fontSize: fontSize.xs, fontWeight: "600", textTransform: "uppercase", letterSpacing: 1 }}>
                  Hackathon Contest
                </Text>
              </View>
              <Text style={{ color: colors.text, fontSize: fontSize.xl, fontWeight: "700", marginBottom: 6 }}>
                {copy.headline}
              </Text>
              <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginBottom: 12 }}>
                {copy.tagline}
              </Text>
              {(copy.highlights || []).map((h, i) => (
                <View key={i} style={{ flexDirection: "row", gap: 8, marginBottom: 6, alignItems: "flex-start" }}>
                  <CheckCircle2 size={14} color={accentColor} style={{ marginTop: 2 }} />
                  <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, flex: 1 }}>{h}</Text>
                </View>
              ))}
              <Divider />
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Clock size={13} color={colors.textDim} />
                <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>
                  {new Date(contest.start_at).toLocaleString()} → {new Date(contest.end_at).toLocaleString()}
                </Text>
              </View>
              <Text style={{ color: colors.textDim, fontSize: fontSize.xs, marginTop: 4 }}>
                {contest.problems.length} problem(s) · status: {contest.status}
              </Text>
            </Card>

            {/* Already registered: confirmation only — no leaderboard, no
                problems, no submission UI. That all stays on the web app. */}
            {contest.my_team ? (
              <Card testID="contest-mobile-already-registered">
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <CheckCircle2 size={18} color={colors.success} />
                  <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: "600" }}>You're registered!</Text>
                </View>
                <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginBottom: 4 }}>
                  Team: {contest.my_team.name} ({contest.my_team.member_user_ids.length} member(s))
                </Text>
                <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>
                  Open the web app to view the leaderboard, solve problems and download your certificate — contest
                  solving is web-only.
                </Text>
              </Card>
            ) : (
              <Card testID="contest-mobile-registration">
                <Text style={{ color: colors.text, fontSize: fontSize.md, fontWeight: "600", marginBottom: 10 }}>
                  Register your team
                </Text>

                {/* Three explicit, distinct paths — not one form that assumes
                    you already have named teammates in hand. */}
                <View style={{ flexDirection: "row", gap: 6, marginBottom: 14 }}>
                  <ModeTab label="Create" Icon={UserPlus} active={mode === "create"} onPress={() => setMode("create")} testID="contest-mobile-mode-create" />
                  <ModeTab label="Join open" Icon={Search} active={mode === "join"} onPress={() => setMode("join")} testID="contest-mobile-mode-join" />
                  <ModeTab label="Solo" Icon={UserIcon} active={mode === "solo"} onPress={() => setMode("solo")} testID="contest-mobile-mode-solo" />
                </View>

                {mode === "create" && (
                  <View style={{ gap: 10 }} testID="contest-mobile-create-form">
                    <View>
                      <Label>Team name</Label>
                      <Input value={teamName} onChangeText={setTeamName} placeholder="Team name" testID="contest-mobile-team-name" />
                    </View>
                    <View>
                      <Label>Teammate email(s) — optional, comma-separated</Label>
                      <Input value={teammateEmails} onChangeText={setTeammateEmails} placeholder="a@example.com, b@example.com" testID="contest-mobile-team-emails" />
                    </View>
                    <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>
                      A team has 1-3 members — you're added automatically, teammates are optional.
                    </Text>
                    <Button
                      title={submitting ? "Registering…" : "Create team"}
                      onPress={() => createTeam(false)}
                      disabled={!teamName.trim() || submitting}
                      loading={submitting}
                      testID="contest-mobile-create-btn"
                    />
                    <Button
                      title="Create + leave open for others to join"
                      variant="outline"
                      onPress={() => createTeam(true)}
                      disabled={!teamName.trim() || submitting}
                      testID="contest-mobile-create-open-btn"
                    />
                  </View>
                )}

                {mode === "join" && (
                  <View style={{ gap: 8 }} testID="contest-mobile-join-form">
                    {loadingOpenTeams && <ActivityIndicator color={colors.primary} />}
                    {!loadingOpenTeams && openTeams?.length === 0 && (
                      <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
                        No open teams yet — create one and leave it open, or register solo.
                      </Text>
                    )}
                    {!loadingOpenTeams && (openTeams || []).map((t) => (
                      <View
                        key={t.id}
                        style={{
                          flexDirection: "row", alignItems: "center", gap: 8,
                          borderWidth: 1, borderColor: colors.border, borderRadius: radii.md,
                          paddingHorizontal: 12, paddingVertical: 10,
                        }}
                        testID={`contest-mobile-open-team-${t.id}`}
                      >
                        <Text style={{ color: colors.text, fontSize: fontSize.sm, flex: 1 }} numberOfLines={1}>{t.name}</Text>
                        <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>{t.member_count}/3</Text>
                        <TouchableOpacity
                          onPress={() => joinOpenTeam(t.id)}
                          disabled={joiningId !== null}
                          style={{
                            paddingHorizontal: 10, paddingVertical: 6, borderRadius: radii.sm,
                            borderWidth: 1, borderColor: colors.primary,
                          }}
                          testID={`contest-mobile-join-btn-${t.id}`}
                        >
                          {joiningId === t.id ? (
                            <ActivityIndicator size="small" color={colors.primary} />
                          ) : (
                            <Text style={{ color: colors.primary, fontSize: fontSize.xs }}>Join ({t.spots_left} left)</Text>
                          )}
                        </TouchableOpacity>
                      </View>
                    ))}
                  </View>
                )}

                {mode === "solo" && (
                  <View style={{ gap: 10 }} testID="contest-mobile-solo-form">
                    <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
                      Don't have teammates yet? Register solo now as a team of one — you can grow your team later.
                    </Text>
                    <Button
                      title={submitting ? "Registering…" : "Register solo"}
                      onPress={registerSolo}
                      disabled={submitting}
                      loading={submitting}
                      testID="contest-mobile-solo-btn"
                    />
                  </View>
                )}
              </Card>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function ModeTab({ label, Icon, active, onPress, testID }) {
  return (
    <TouchableOpacity
      onPress={onPress}
      testID={testID}
      style={{
        flex: 1, alignItems: "center", gap: 4, paddingVertical: 8, borderRadius: radii.md,
        backgroundColor: active ? colors.surfaceElevated : "transparent",
        borderWidth: 1, borderColor: active ? colors.primary : colors.border,
      }}
    >
      <Icon size={14} color={active ? colors.primary : colors.textMuted} />
      <Text style={{ color: active ? colors.primary : colors.textMuted, fontSize: fontSize.xs, fontWeight: "500" }}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}
