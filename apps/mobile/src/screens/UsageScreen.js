import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, RefreshControl, TouchableOpacity } from 'react-native';
import api from '../api';
import ScreenHeader from '../components/ScreenHeader';
import { Card, StatCard } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';

const PERIODS = [
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
  { key: '90d', label: '90d' },
  { key: 'lifetime', label: 'All' },
];

export default function UsageScreen({ navigation }) {
  const [summary, setSummary] = useState(null);
  const [period, setPeriod] = useState('30d');
  const [timeline, setTimeline] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    setRefreshing(true);
    try {
      const [s, t] = await Promise.all([
        api.get('/usage/summary'),
        api.get(`/usage/timeline?period=${period}`),
      ]);
      setSummary(s.data);
      setTimeline(t.data.items);
    } catch {} finally { setRefreshing(false); }
  };
  useEffect(() => { load(); }, [period]);

  const maxCredits = Math.max(...timeline.map(t => t.credits), 1);

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenHeader title="Usage" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.primary} />}>
        <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
          {PERIODS.map(p => (
            <TouchableOpacity key={p.key} onPress={() => setPeriod(p.key)}
              style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: radii.md, borderWidth: 1, borderColor: period === p.key ? colors.primary : colors.border, backgroundColor: period === p.key ? colors.primaryDim : 'transparent' }}>
              <Text style={{ color: period === p.key ? colors.primary : colors.textMuted, fontSize: fontSize.sm }}>{p.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <View style={{ flexDirection: 'row', gap: spacing.sm }}>
          <StatCard label="Today" value={summary ? Math.floor(summary.credits_used_today) : 0} sub={`${summary?.requests_today || 0} reqs`} />
          <StatCard label="Week" value={summary ? Math.floor(summary.credits_used_week) : 0} sub={`${summary?.requests_week || 0} reqs`} />
        </View>
        <View style={{ flexDirection: 'row', gap: spacing.sm }}>
          <StatCard label="Month" value={summary ? Math.floor(summary.credits_used_month) : 0} sub={`${summary?.requests_month || 0} reqs`} />
          <StatCard label="Lifetime" value={summary ? Math.floor(summary.credits_used_lifetime) : 0} sub={`${summary?.requests_lifetime || 0} reqs`} />
        </View>

        <Card>
          <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginBottom: spacing.md }}>Timeline</Text>
          {timeline.length === 0 ? (
            <Text style={{ color: colors.textMuted, textAlign: 'center', paddingVertical: 24 }}>No usage yet in this period</Text>
          ) : (
            <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 4, height: 140 }}>
              {timeline.slice(-14).map((t) => (
                <View key={t.date} style={{ flex: 1, alignItems: 'center', gap: 4 }}>
                  <View style={{ width: '100%', height: `${(t.credits / maxCredits) * 100}%`, backgroundColor: colors.primary, borderRadius: 3, minHeight: 3 }} />
                  <Text style={{ color: colors.textDim, fontSize: 9 }}>{t.date.slice(5)}</Text>
                </View>
              ))}
            </View>
          )}
        </Card>

        <Card>
          <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginBottom: 8 }}>Insights</Text>
          <InsightRow label="Avg credits/request" value={summary?.avg_credits_per_request ?? '—'} />
          <InsightRow label="Top provider" value={summary?.most_used_provider || '—'} />
          <InsightRow label="Top model" value={summary?.most_used_model || '—'} />
        </Card>
      </ScrollView>
    </View>
  );
}

function InsightRow({ label, value }) {
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8, borderBottomWidth: 1, borderColor: colors.border + '80' }}>
      <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>{label}</Text>
      <Text style={{ color: colors.text, fontSize: fontSize.sm, fontWeight: '500' }}>{value}</Text>
    </View>
  );
}
