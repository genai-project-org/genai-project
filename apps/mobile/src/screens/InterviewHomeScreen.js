import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ScrollView, ActivityIndicator, Alert, TouchableOpacity } from 'react-native';
import { useDispatch, useSelector } from 'react-redux';
import * as WebBrowser from 'expo-web-browser';
import { Mic, ChevronRight, Award } from 'lucide-react-native';
import api from '../api';
import {
  getEntitlement,
  listSessions,
  listInterviewPacks,
} from '../services/interviewApi';
import { setEntitlement, setActiveSession } from '../store/slices/interviewSlice';
import ScreenHeader from '../components/ScreenHeader';
import { Card, Button } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';

const IN_PROGRESS_STATUSES = ['created', 'technical_in_progress', 'behavioral_in_progress'];

export default function InterviewHomeScreen({ navigation }) {
  const dispatch = useDispatch();
  const entitlement = useSelector((s) => s.interview.entitlement);
  const [sessions, setSessions] = useState([]);
  const [packs, setPacks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [buying, setBuying] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [entRes, sessRes, packsRes] = await Promise.allSettled([
        getEntitlement(),
        listSessions(20),
        listInterviewPacks('usd'),
      ]);
      if (entRes.status === 'fulfilled') dispatch(setEntitlement(entRes.value));
      if (sessRes.status === 'fulfilled') setSessions(sessRes.value.items || []);
      if (packsRes.status === 'fulfilled') setPacks(packsRes.value.items || []);
    } finally {
      setLoading(false);
    }
  }, [dispatch]);

  useEffect(() => {
    load();
  }, [load]);

  const activeSession = sessions.find((s) => IN_PROGRESS_STATUSES.includes(s.status));

  const startNew = () => {
    if (activeSession) {
      Alert.alert(
        'Interview already in progress',
        'You have an active Mock Interview session. Resume it to continue.',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Resume', onPress: () => resumeSession(activeSession) },
        ]
      );
      return;
    }
    if (entitlement && entitlement.sessions_remaining <= 0) {
      Alert.alert('No sessions left', 'Buy an Interview Pack below to start a new Mock Interview.');
      return;
    }
    navigation.navigate('InterviewSetup');
  };

  const resumeSession = (session) => {
    dispatch(setActiveSession({ id: session.id, topic: session.topic, phase: 'live' }));
    navigation.navigate('InterviewSession', { sessionId: session.id });
  };

  const openHostedCheckout = async (shortUrl, onSettled) => {
    try {
      const result = await WebBrowser.openBrowserAsync(shortUrl, {
        dismissButtonStyle: 'close',
        controlsColor: colors.primary,
      });
      if (result?.type === 'dismiss' || result?.type === 'cancel') {
        await onSettled?.();
      }
    } catch (e) {
      Alert.alert('Checkout error', String(e?.message || e));
    }
  };

  const buyPack = async (pack) => {
    setBuying(pack.slug);
    try {
      const { data } = await api.post('/payments/razorpay/order', {
        pack_slug: pack.slug,
        pack_kind: 'interview_sessions',
      });
      if (!data?.short_url) throw new Error('No checkout URL returned');
      await openHostedCheckout(data.short_url, async () => {
        try {
          const { data: st } = await api.get(`/payments/razorpay/link-status/${data.payment_link_id}`);
          if (st.status === 'paid') {
            Alert.alert('Purchase successful', `${pack.sessions_included} interview session(s) added.`);
            load();
          } else if (st.status === 'cancelled' || st.status === 'expired') {
            Alert.alert('Payment not completed', 'The checkout was cancelled or expired.');
          } else {
            Alert.alert('Payment pending', 'Your sessions will appear shortly. Pull to refresh.');
          }
        } catch {
          Alert.alert('Verification pending', 'Please check back shortly.');
        }
      });
    } catch (err) {
      Alert.alert('Payment failed', err.response?.data?.detail || err.message || 'Try again');
    } finally {
      setBuying(null);
    }
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        <ScreenHeader title="Mock Interviews" navigation={navigation} />
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }} testID="interview-home-screen">
      <ScreenHeader title="Mock Interviews" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        <Card>
          <Text style={{ color: colors.textDim, fontSize: fontSize.xs, textTransform: 'uppercase', letterSpacing: 1 }}>
            Sessions remaining
          </Text>
          <Text style={{ color: colors.text, fontSize: 32, fontWeight: '700', marginTop: 4 }}>
            {entitlement ? entitlement.sessions_remaining : '—'}
          </Text>
          {!!entitlement?.grants?.length && (
            <View style={{ marginTop: spacing.sm, gap: 4 }}>
              {entitlement.grants.map((g) => (
                <Text key={g.grant_id} style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
                  {g.pack_name}: {g.sessions_remaining} of {g.sessions_total} left
                </Text>
              ))}
            </View>
          )}
          <Button
            title={activeSession ? 'Resume Interview' : 'Start New Interview'}
            onPress={startNew}
            style={{ marginTop: spacing.lg }}
            testID="interview-start-btn"
          />
        </Card>

        <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600' }}>
          Interview Packs
        </Text>
        {packs.length === 0 && (
          <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>No packs available right now.</Text>
        )}
        {packs.map((p) => (
          <View key={p.slug} style={cardStyle(p.is_popular)}>
            {p.is_popular && (
              <View style={{ position: 'absolute', top: -10, right: 14, backgroundColor: colors.primary, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 }}>
                <Text style={{ color: '#fff', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, fontWeight: '600' }}>Popular</Text>
              </View>
            )}
            <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>{p.name}</Text>
            <Text style={{ color: colors.text, fontSize: 28, fontWeight: '600', marginTop: 4 }}>
              ${Number(p.price).toFixed(2)}
            </Text>
            <Text style={{ color: colors.textMuted, marginTop: 2 }}>
              {p.sessions_included} interview session{p.sessions_included === 1 ? '' : 's'}
            </Text>
            {!!p.description && (
              <Text style={{ color: colors.textDim, fontSize: fontSize.xs, marginTop: 6 }}>{p.description}</Text>
            )}
            <Button
              title={`Buy ${p.name}`}
              loading={buying === p.slug}
              onPress={() => buyPack(p)}
              variant={p.is_popular ? 'primary' : 'outline'}
              style={{ marginTop: spacing.md }}
              testID={`buy-pack-${p.slug}`}
            />
          </View>
        ))}

        <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginTop: spacing.md }}>
          Session history
        </Text>
        {sessions.length === 0 && (
          <Card>
            <Text style={{ color: colors.textMuted }}>No interviews yet.</Text>
          </Card>
        )}
        {sessions.map((s) => (
          <TouchableOpacity
            key={s.id}
            disabled={!s.final_report_id}
            onPress={() => navigation.navigate('InterviewReport', { sessionId: s.id })}
          >
            <Card style={{ flexDirection: 'row', alignItems: 'center' }}>
              <View
                style={{
                  height: 36, width: 36, borderRadius: radii.md, backgroundColor: colors.primaryDim,
                  alignItems: 'center', justifyContent: 'center', marginRight: spacing.md,
                }}
              >
                {s.final_report_id ? (
                  <Award color={colors.primary} size={18} />
                ) : (
                  <Mic color={colors.primary} size={18} />
                )}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ color: colors.text, fontWeight: '600', textTransform: 'uppercase' }}>{s.topic}</Text>
                <Text style={{ color: colors.textMuted, fontSize: fontSize.xs, marginTop: 2 }}>
                  {statusLabel(s.status)} · {formatDate(s.created_at)}
                </Text>
              </View>
              {!!s.final_report_id && <ChevronRight color={colors.textMuted} size={18} />}
            </Card>
          </TouchableOpacity>
        ))}
      </ScrollView>
    </View>
  );
}

function statusLabel(status) {
  return {
    created: 'Not started',
    technical_in_progress: 'In progress (technical)',
    behavioral_in_progress: 'In progress (behavioral)',
    completed: 'Completed',
    terminated_violations: 'Ended — proctoring violations',
    terminated_error: 'Ended — error',
    abandoned: 'Abandoned',
    expired: 'Expired',
  }[status] || status;
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return '';
  }
}

const cardStyle = (popular) => ({
  borderWidth: 1,
  borderColor: popular ? colors.primary : colors.border,
  borderRadius: radii.lg,
  backgroundColor: colors.card,
  padding: spacing.lg,
  position: 'relative',
});
