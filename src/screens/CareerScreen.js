import React, { useState } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  Linking,
} from "react-native";
import {
  Briefcase,
  MapPin,
  IndianRupee,
  GraduationCap,
  ExternalLink,
} from "lucide-react-native";
import api from "../api";
import ScreenHeader from "../components/ScreenHeader";
import { Card, Button, Input, Label } from "../components/UI";
import { colors, spacing, fontSize, radii } from "../theme";
import ReportButton from "../components/ReportButton";

export default function CareerScreen({ navigation }) {
  const [tab, setTab] = useState("jobs");
  return (
    <View
      style={{ flex: 1, backgroundColor: colors.bg }}
      testID="career-screen"
    >
      <ScreenHeader title="Career Intelligence" navigation={navigation} />
      <View
        style={{
          flexDirection: "row",
          paddingHorizontal: spacing.md,
          paddingTop: spacing.md,
          gap: 8,
        }}
      >
        <TabBtn
          label="Jobs"
          Icon={Briefcase}
          active={tab === "jobs"}
          onPress={() => setTab("jobs")}
        />
        <TabBtn
          label="Learning Path"
          Icon={GraduationCap}
          active={tab === "path"}
          onPress={() => setTab("path")}
        />
      </View>
      <ScrollView
        contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
      >
        {tab === "jobs" ? <Jobs /> : <Path />}
      </ScrollView>
    </View>
  );
}

function TabBtn({ label, Icon, active, onPress }) {
  return (
    <TouchableOpacity
      onPress={onPress}
      style={{
        flex: 1,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        paddingVertical: 10,
        borderRadius: radii.md,
        borderWidth: 1,
        borderColor: active ? colors.primary : colors.border,
        backgroundColor: active ? colors.primaryDim : "transparent",
      }}
    >
      <Icon color={active ? colors.primary : colors.textMuted} size={14} />
      <Text
        style={{
          color: active ? colors.primary : colors.textMuted,
          fontSize: fontSize.sm,
          fontWeight: "500",
        }}
      >
        {label}
      </Text>
    </TouchableOpacity>
  );
}

function Jobs() {
  const [query, setQuery] = useState("python developer");
  const [loc, setLoc] = useState("Bengaluru");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/career/jobs", {
        query,
        location: loc,
        page: 1,
      });
      setItems(data.results || []);
    } catch {
    } finally {
      setLoading(false);
    }
  };
  return (
    <>
      <Card>
        <Label>Role or skill</Label>
        <Input
          value={query}
          onChangeText={setQuery}
          placeholder="e.g. React developer"
        />
        <Label>Location</Label>
        <Input value={loc} onChangeText={setLoc} placeholder="City" />
        <Button
          title="Search Jobs"
          onPress={run}
          loading={loading}
          style={{ marginTop: spacing.md }}
          testID="career-jobs-search-btn"
        />
      </Card>
      {items.map((j) => (
        <TouchableOpacity
          key={j.id}
          onPress={() => j.url && Linking.openURL(j.url)}
        >
          <Card>
            <View
              style={{ flexDirection: "row", justifyContent: "space-between" }}
            >
              <View style={{ flex: 1 }}>
                <Text
                  style={{
                    color: colors.text,
                    fontSize: fontSize.md,
                    fontWeight: "500",
                  }}
                  numberOfLines={1}
                >
                  {j.title}
                </Text>
                <Text
                  style={{ color: colors.textMuted, fontSize: fontSize.sm }}
                >
                  {j.company}
                </Text>
              </View>
              <ExternalLink color={colors.textMuted} size={14} />
            </View>
            <View style={{ flexDirection: "row", gap: 12, marginTop: 6 }}>
              {j.location ? <Row Icon={MapPin} text={j.location} /> : null}
              {j.salary_min ? (
                <Row
                  Icon={IndianRupee}
                  text={`${Math.round(j.salary_min / 100000)}–${Math.round(
                    (j.salary_max || j.salary_min) / 100000
                  )} LPA`}
                />
              ) : null}
            </View>
            <Text
              style={{
                color: colors.textDim,
                fontSize: fontSize.xs,
                marginTop: 8,
              }}
              numberOfLines={3}
            >
              {j.description}
            </Text>
          </Card>
        </TouchableOpacity>
      ))}
    </>
  );
}

function Row({ Icon, text }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <Icon color={colors.textDim} size={12} />
      <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>
        {text}
      </Text>
    </View>
  );
}

function Path() {
  const [role, setRole] = useState("");
  const [skills, setSkills] = useState("");
  const [out, setOut] = useState("");
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const run = async () => {
    if (!role.trim()) return;
    setLoading(true);
    setOut("");
    try {
      const skillsArr = skills
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const response = await api.post("/career/learning-path", {
        role,
        skills: skillsArr,
      });

      console.log("Career Response:", response.data);

      const data = response.data;
      setOut(data.roadmap_markdown);
      setMeta({ cached: data.cached, credits: data.credits_used });
    } catch (e) {
      setOut("Failed: " + (e.response?.data?.detail || "error"));
    } finally {
      setLoading(false);
    }
  };
  return (
    <>
      <Card>
        <Label>Target role</Label>
        <Input
          value={role}
          onChangeText={setRole}
          placeholder="e.g. Backend Python Engineer"
        />
        <Label>Current skills (comma-separated)</Label>
        <Input
          value={skills}
          onChangeText={setSkills}
          placeholder="python, git"
        />
        <Text
          style={{ color: colors.textDim, fontSize: fontSize.xs, marginTop: 6 }}
        >
          5 credits · cached after first generation
        </Text>
        <Button
          title="Generate Path"
          onPress={run}
          loading={loading}
          disabled={!role.trim()}
          style={{ marginTop: spacing.md }}
          testID="career-path-btn"
        />
      </Card>
      {meta ? (
        <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>
          {meta.cached ? "✓ Cached (free)" : `Fresh · ${meta.credits} credits`}
        </Text>
      ) : null}
      {out ? (
        <Card>
          <Text
            style={{
              color: colors.text,
              fontSize: fontSize.sm,
              lineHeight: 20,
            }}
          >
            {out}
          </Text>
          <ReportButton />
        </Card>
      ) : null}
    </>
  );
}
