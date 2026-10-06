import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, ScrollView, TouchableOpacity, ActivityIndicator, Alert, Switch } from 'react-native';
import { useDispatch } from 'react-redux';
import * as DocumentPicker from 'expo-document-picker';
import { Code2, Layers, Boxes, PenTool, Users, Check, Monitor, Package } from 'lucide-react-native';
import {
  getEntitlement,
  getResumeProfile,
  saveResumeProfileFile,
  saveResumeProfileText,
  createSession,
} from '../services/interviewApi';
import { setEntitlement, setActiveSession } from '../store/slices/interviewSlice';
import ScreenHeader from '../components/ScreenHeader';
import { Card, Button, Input, Label } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';

// Metadata (icon/label) for every topic the backend can allow — actual
// availability per session is driven entirely by the selected grant's
// `config.topics`, since interviews are configurable per-pack.
const TOPIC_META = {
  dsa: { label: 'DSA / Live Coding', Icon: Code2, gated: true },
  hld: { label: 'High-Level Design', Icon: Layers },
  lld: { label: 'Low-Level Design', Icon: Boxes },
  design: { label: 'System Design', Icon: PenTool },
  hr: { label: 'Behavioral / HR', Icon: Users },
};
const SENIORITY_LABELS = { entry: 'Entry', mid: 'Mid', senior: 'Senior' };

export default function InterviewSetupScreen({ navigation }) {
  const dispatch = useDispatch();
  const [loadingEntitlement, setLoadingEntitlement] = useState(true);
  const [grants, setGrants] = useState([]);
  const [selectedGrant, setSelectedGrant] = useState(null);

  const [topic, setTopic] = useState(null);
  const [subTopic, setSubTopic] = useState(null);
  const [seniority, setSeniority] = useState(null);
  const [includeBehavioral, setIncludeBehavioral] = useState(true);

  const [profile, setProfile] = useState(null);
  const [loadingProfile, setLoadingProfile] = useState(true);
  const [useExisting, setUseExisting] = useState(true);
  const [pastedText, setPastedText] = useState('');
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const entitlement = await getEntitlement();
        dispatch(setEntitlement(entitlement));
        const g = entitlement.grants || [];
        setGrants(g);
        if (g.length === 1) selectGrant(g[0]);
      } catch {
        setGrants([]);
      } finally {
        setLoadingEntitlement(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const { profile } = await getResumeProfile();
        setProfile(profile);
        setUseExisting(!!profile);
      } catch {
        // Non-fatal — interview can still start without a linked résumé.
      } finally {
        setLoadingProfile(false);
      }
    })();
  }, []);

  const selectGrant = (grant) => {
    setSelectedGrant(grant);
    setTopic(null);
    setSubTopic(null);
    setSeniority(grant.config.seniority_levels?.[0] || null);
    setIncludeBehavioral((grant.config.behavioral_minutes || 0) > 0);
  };

  const availableTopics = useMemo(
    () => (selectedGrant?.config.topics || []).filter((t) => TOPIC_META[t]),
    [selectedGrant]
  );
  const availableSeniorities = selectedGrant?.config.seniority_levels || [];
  const subTopicOptions = (topic && selectedGrant?.config.sub_topics?.[topic]) || [];
  const canIncludeBehavioral = (selectedGrant?.config.behavioral_minutes || 0) > 0;

  const pickResume = async () => {
    const res = await DocumentPicker.getDocumentAsync({
      type: [
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      ],
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (res.canceled || !res.assets?.[0]) return;
    const asset = res.assets[0];
    setUploading(true);
    try {
      const { profile: saved } = await saveResumeProfileFile({
        uri: asset.uri,
        name: asset.name,
        mimeType: asset.mimeType,
      });
      setProfile(saved);
      setUseExisting(true);
    } catch (err) {
      Alert.alert('Upload failed', err.response?.data?.detail || 'Could not process that résumé.');
    } finally {
      setUploading(false);
    }
  };

  const savePastedText = async () => {
    if (!pastedText.trim()) return;
    setUploading(true);
    try {
      const { profile: saved } = await saveResumeProfileText(pastedText.trim());
      setProfile(saved);
      setUseExisting(true);
      setPastedText('');
    } catch (err) {
      Alert.alert('Save failed', err.response?.data?.detail || 'Could not process that résumé text.');
    } finally {
      setUploading(false);
    }
  };

  const start = async () => {
    if (!selectedGrant) return;
    if (!topic) {
      Alert.alert('Choose a topic', 'Select an interview topic to continue.');
      return;
    }
    if (topic === 'dsa') return; // gated — button already disabled, this is a safety net
    setStarting(true);
    try {
      const resume_profile_id = useExisting && profile ? profile.id : undefined;
      const session = await createSession({
        grant_id: selectedGrant.grant_id,
        topic,
        seniority,
        sub_topic: subTopicOptions.length ? subTopic || undefined : undefined,
        include_behavioral: canIncludeBehavioral ? includeBehavioral : undefined,
        resume_profile_id,
      });
      dispatch(
        setActiveSession({ id: session.id, topic: session.topic, phase: 'system_check' })
      );
      navigation.navigate('InterviewSystemCheck', { sessionId: session.id });
    } catch (err) {
      const status = err.response?.status;
      if (status === 402) {
        Alert.alert('No sessions left', 'Buy an Interview Pack to start a new Mock Interview.');
        navigation.goBack();
      } else if (status === 409) {
        Alert.alert('Interview already in progress', 'You already have an active session. Resume it from the Mock Interviews home screen.');
        navigation.goBack();
      } else if (status === 400) {
        Alert.alert('Not available on this pack', err.response?.data?.detail || err.response?.data || 'That combination isn’t allowed by the selected pack.');
      } else {
        Alert.alert('Could not start interview', err.response?.data?.detail || err.message);
      }
    } finally {
      setStarting(false);
    }
  };

  if (loadingEntitlement) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        <ScreenHeader title="Set up your interview" navigation={navigation} />
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      </View>
    );
  }

  if (grants.length === 0) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        <ScreenHeader title="Set up your interview" navigation={navigation} />
        <View style={{ padding: spacing.md }}>
          <Card>
            <Text style={{ color: colors.text, fontWeight: '600', marginBottom: 6 }}>No sessions available</Text>
            <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
              Buy an Interview Pack from the Mock Interviews home screen to start a session.
            </Text>
          </Card>
        </View>
      </View>
    );
  }

  // Multiple packs owned and none chosen yet — let the candidate pick which
  // one to spend a session from, since each grant has its own config.
  if (!selectedGrant) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }} testID="interview-grant-picker">
        <ScreenHeader title="Choose a pack to use" navigation={navigation} />
        <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.sm }}>
          {grants.map((g) => (
            <TouchableOpacity key={g.grant_id} onPress={() => selectGrant(g)} testID={`grant-${g.grant_id}`}>
              <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                <Package color={colors.primary} size={20} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: colors.text, fontWeight: '600' }}>{g.pack_name}</Text>
                  <Text style={{ color: colors.textMuted, fontSize: fontSize.xs, marginTop: 2 }}>
                    {g.sessions_remaining} of {g.sessions_total} sessions left
                  </Text>
                </View>
              </Card>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }} testID="interview-setup-screen">
      <ScreenHeader title="Set up your interview" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.lg }}>
        {grants.length > 1 && (
          <TouchableOpacity onPress={() => setSelectedGrant(null)}>
            <Text style={{ color: colors.primary, fontSize: fontSize.sm }}>
              Using {selectedGrant.pack_name} · change pack
            </Text>
          </TouchableOpacity>
        )}

        <View>
          <Text style={sectionTitle}>Topic</Text>
          <View style={{ gap: spacing.sm }}>
            {availableTopics.map((id) => {
              const { label, Icon, gated } = TOPIC_META[id];
              const active = topic === id;
              return (
                <TouchableOpacity
                  key={id}
                  onPress={() => { setTopic(id); setSubTopic(null); }}
                  testID={`topic-${id}`}
                  style={{
                    flexDirection: 'row', alignItems: 'center', gap: 12,
                    borderWidth: 1, borderColor: active ? colors.primary : colors.border,
                    backgroundColor: active ? colors.primaryDim : colors.card,
                    borderRadius: radii.lg, padding: spacing.md,
                  }}
                >
                  <Icon color={active ? colors.primary : colors.textMuted} size={20} />
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: active ? colors.text : colors.textMuted, fontWeight: '600' }}>
                      {label}
                    </Text>
                    {gated && (
                      <Text style={{ color: colors.warning, fontSize: fontSize.xs, marginTop: 2 }}>
                        Web only for now
                      </Text>
                    )}
                  </View>
                  {active && <Check color={colors.primary} size={18} />}
                </TouchableOpacity>
              );
            })}
          </View>
          {topic === 'dsa' && (
            <Card style={{ marginTop: spacing.sm, borderColor: colors.warning, flexDirection: 'row', gap: 10 }}>
              <Monitor color={colors.warning} size={18} />
              <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, flex: 1 }}>
                DSA coding rounds need a full keyboard and code editor — please continue this one on
                web. Pick a different topic here to start on mobile.
              </Text>
            </Card>
          )}
        </View>

        {!!subTopicOptions.length && (
          <View>
            <Text style={sectionTitle}>Focus area (optional)</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
              {subTopicOptions.map((st) => {
                const active = subTopic === st;
                return (
                  <TouchableOpacity
                    key={st}
                    onPress={() => setSubTopic(active ? null : st)}
                    testID={`subtopic-${st}`}
                    style={{
                      paddingHorizontal: 12, paddingVertical: 8, borderRadius: radii.full,
                      borderWidth: 1, borderColor: active ? colors.primary : colors.border,
                      backgroundColor: active ? colors.primaryDim : 'transparent',
                    }}
                  >
                    <Text style={{ color: active ? colors.primary : colors.textMuted, fontSize: fontSize.sm }}>
                      {st.replace(/_/g, ' ')}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>
        )}

        <View>
          <Text style={sectionTitle}>Seniority</Text>
          <View style={{ flexDirection: 'row', gap: spacing.sm }}>
            {availableSeniorities.map((id) => {
              const active = seniority === id;
              return (
                <TouchableOpacity
                  key={id}
                  onPress={() => setSeniority(id)}
                  testID={`seniority-${id}`}
                  style={{
                    flex: 1, alignItems: 'center', paddingVertical: 10, borderRadius: radii.md,
                    borderWidth: 1, borderColor: active ? colors.primary : colors.border,
                    backgroundColor: active ? colors.primaryDim : 'transparent',
                  }}
                >
                  <Text style={{ color: active ? colors.primary : colors.textMuted, fontWeight: '500' }}>
                    {SENIORITY_LABELS[id] || id}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>

        {canIncludeBehavioral && (
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <View style={{ flex: 1, paddingRight: spacing.md }}>
              <Text style={{ color: colors.text, fontWeight: '500' }}>Include behavioral round</Text>
              <Text style={{ color: colors.textMuted, fontSize: fontSize.xs, marginTop: 2 }}>
                {selectedGrant.config.technical_minutes}min technical
                {includeBehavioral ? ` + ${selectedGrant.config.behavioral_minutes}min behavioral` : ''}
              </Text>
            </View>
            <Switch
              value={includeBehavioral}
              onValueChange={setIncludeBehavioral}
              trackColor={{ true: colors.primary }}
              testID="include-behavioral-switch"
            />
          </View>
        )}

        <View>
          <Text style={sectionTitle}>Résumé (optional but recommended)</Text>
          {loadingProfile ? (
            <ActivityIndicator color={colors.primary} />
          ) : profile ? (
            <Card>
              <TouchableOpacity
                onPress={() => setUseExisting((v) => !v)}
                style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}
                testID="use-existing-resume-toggle"
              >
                <View
                  style={{
                    width: 20, height: 20, borderRadius: 5, borderWidth: 1.5,
                    borderColor: useExisting ? colors.primary : colors.border,
                    backgroundColor: useExisting ? colors.primary : 'transparent',
                    alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  {useExisting && <Check color="#fff" size={13} />}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: colors.text, fontWeight: '500' }}>
                    Use my saved résumé{profile.filename ? ` (${profile.filename})` : ''}
                  </Text>
                  {profile.ats_score != null && (
                    <Text style={{ color: colors.textDim, fontSize: fontSize.xs, marginTop: 2 }}>
                      ATS score {profile.ats_score}
                    </Text>
                  )}
                </View>
              </TouchableOpacity>
              <Button
                title="Replace résumé"
                variant="outline"
                onPress={pickResume}
                loading={uploading}
                style={{ marginTop: spacing.md }}
              />
            </Card>
          ) : (
            <Card>
              <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginBottom: spacing.md }}>
                Link a résumé so the interviewer can ask about your real experience.
              </Text>
              <Button
                title="Upload PDF / DOCX"
                onPress={pickResume}
                loading={uploading}
                testID="upload-resume-btn"
              />
              <View style={{ marginTop: spacing.md }}>
                <Label>Or paste résumé text</Label>
                <Input
                  value={pastedText}
                  onChangeText={setPastedText}
                  placeholder="Paste your résumé text here..."
                  multiline
                  style={{ minHeight: 100, textAlignVertical: 'top' }}
                />
                <Button
                  title="Save résumé text"
                  variant="outline"
                  onPress={savePastedText}
                  loading={uploading}
                  disabled={!pastedText.trim()}
                  style={{ marginTop: spacing.sm }}
                />
              </View>
            </Card>
          )}
        </View>

        <Button
          title={starting ? 'Starting…' : 'Continue'}
          onPress={start}
          loading={starting}
          disabled={!topic || topic === 'dsa'}
          testID="interview-setup-continue-btn"
        />
      </ScrollView>
    </View>
  );
}

const sectionTitle = {
  color: colors.textDim,
  fontSize: fontSize.xs,
  textTransform: 'uppercase',
  letterSpacing: 1,
  marginBottom: spacing.sm,
};
