import React, { useEffect, useRef, useState } from 'react';
import { View, Text, ScrollView, ActivityIndicator } from 'react-native';
import Markdown from 'react-native-markdown-display';
import Animated, { useSharedValue, useAnimatedStyle, withTiming, withDelay } from 'react-native-reanimated';
import { ShieldCheck, ThumbsUp, ThumbsDown } from 'lucide-react-native';
import { getReport } from '../services/interviewApi';
import ScreenHeader from '../components/ScreenHeader';
import InterviewScoreChart from '../components/InterviewScoreChart';
import { Card, Button } from '../components/UI';
import { colors, spacing, fontSize } from '../theme';

const REPORT_POLL_MS = 5000;

export default function InterviewReportScreen({ navigation, route }) {
  const { sessionId } = route.params || {};
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef(null);

  const reveal = useSharedValue(0);

  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const data = await getReport(sessionId);
        if (!mounted) return;
        setReport(data);
        setLoading(false);
        if (data.status === 'ready' && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          reveal.value = withDelay(150, withTiming(1, { duration: 600 }));
        }
      } catch {
        if (mounted) setLoading(false);
      }
    };
    poll();
    pollRef.current = setInterval(poll, REPORT_POLL_MS);
    return () => {
      mounted = false;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [sessionId, reveal]);

  const revealStyle = useAnimatedStyle(() => ({
    opacity: reveal.value,
    transform: [{ translateY: (1 - reveal.value) * 16 }],
  }));

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        <ScreenHeader title="Interview Report" navigation={navigation} />
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      </View>
    );
  }

  if (!report || report.status === 'pending') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }} testID="interview-report-pending">
        <ScreenHeader title="Interview Report" navigation={navigation} />
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl }}>
          <ActivityIndicator color={colors.primary} />
          <Text style={{ color: colors.textMuted, marginTop: spacing.md, textAlign: 'center' }}>
            Generating your report — this can take a minute…
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }} testID="interview-report-ready">
      <ScreenHeader title="Interview Report" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.lg }}>
        <Animated.View style={revealStyle}>
          <Card>
            <InterviewScoreChart
              overallScore={report.overall_score}
              dimensionScores={report.dimension_scores}
            />
          </Card>
        </Animated.View>

        <Animated.View style={[{ gap: spacing.md }, revealStyle]}>
          {!!report.strengths?.length && (
            <Card>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: spacing.sm }}>
                <ThumbsUp color={colors.success} size={18} />
                <Text style={{ color: colors.text, fontWeight: '600' }}>Strengths</Text>
              </View>
              {report.strengths.map((s, i) => (
                <Text key={i} style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>
                  • {s}
                </Text>
              ))}
            </Card>
          )}

          {!!report.weaknesses?.length && (
            <Card>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: spacing.sm }}>
                <ThumbsDown color={colors.warning} size={18} />
                <Text style={{ color: colors.text, fontWeight: '600' }}>Areas to improve</Text>
              </View>
              {report.weaknesses.map((s, i) => (
                <Text key={i} style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>
                  • {s}
                </Text>
              ))}
            </Card>
          )}

          {!!report.proctoring_summary && (
            <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
              <ShieldCheck color={colors.primary} size={18} />
              <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, flex: 1 }}>
                {report.proctoring_summary.violation_count === 0
                  ? 'No proctoring violations were recorded during this session.'
                  : `${report.proctoring_summary.violation_count} proctoring violation(s) were recorded during this session.`}
              </Text>
            </Card>
          )}

          {!!report.report_markdown && (
            <Card>
              <Markdown style={mdStyles}>{report.report_markdown}</Markdown>
            </Card>
          )}

          <Button
            title="View Career Intelligence"
            variant="outline"
            onPress={() => navigation.navigate('Career Intelligence')}
            style={{ flexDirection: 'row', gap: 8 }}
          />
        </Animated.View>
      </ScrollView>
    </View>
  );
}

const mdStyles = {
  body: { color: colors.text, fontSize: fontSize.sm, lineHeight: 20 },
  heading1: { color: colors.text, fontSize: fontSize.lg, fontWeight: '700', marginVertical: 8 },
  heading2: { color: colors.text, fontSize: fontSize.md, fontWeight: '600', marginVertical: 6 },
  heading3: { color: colors.text, fontSize: fontSize.md, fontWeight: '600', marginVertical: 4 },
  bullet_list_icon: { color: colors.primary },
  link: { color: colors.primary },
};
