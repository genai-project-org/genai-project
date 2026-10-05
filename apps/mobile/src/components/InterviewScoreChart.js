import React from 'react';
import { View, Text } from 'react-native';
import Svg, { Circle, G, Text as SvgText } from 'react-native-svg';
import { colors, spacing, fontSize, radii } from '../theme';

const DIMENSION_LABELS = {
  communication: 'Communication',
  technical_correctness: 'Technical',
  problem_solving: 'Problem Solving',
  confidence: 'Confidence',
  proctoring_integrity: 'Integrity',
};

/**
 * Simple ring + bar visualization for the report's dimension_scores +
 * overall_score. Deliberately built with react-native-svg (already a
 * dependency) rather than pulling in a charting library for a handful of
 * shapes.
 */
export default function InterviewScoreChart({ overallScore = 0, dimensionScores = {} }) {
  const entries = Object.entries(dimensionScores).filter(([k]) => DIMENSION_LABELS[k]);
  const size = 140;
  const stroke = 12;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(100, overallScore)) / 100;
  const dashOffset = circumference * (1 - pct);

  return (
    <View>
      <View style={{ alignItems: 'center' }}>
        <Svg width={size} height={size}>
          <G rotation="-90" origin={`${size / 2}, ${size / 2}`}>
            <Circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              stroke={colors.border}
              strokeWidth={stroke}
              fill="none"
            />
            <Circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              stroke={colors.primary}
              strokeWidth={stroke}
              strokeDasharray={`${circumference} ${circumference}`}
              strokeDashoffset={dashOffset}
              strokeLinecap="round"
              fill="none"
            />
          </G>
          <SvgText
            x={size / 2}
            y={size / 2 + 8}
            fontSize={28}
            fontWeight="700"
            fill={colors.text}
            textAnchor="middle"
          >
            {Math.round(overallScore)}
          </SvgText>
        </Svg>
        <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>
          Overall score / 100
        </Text>
      </View>

      <View style={{ marginTop: spacing.lg, gap: spacing.sm }}>
        {entries.map(([key, value]) => (
          <ScoreBar key={key} label={DIMENSION_LABELS[key]} value={value} />
        ))}
      </View>
    </View>
  );
}

function ScoreBar({ label, value }) {
  const pct = Math.max(0, Math.min(100, value || 0));
  return (
    <View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
        <Text style={{ color: colors.text, fontSize: fontSize.sm }}>{label}</Text>
        <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>{Math.round(pct)}</Text>
      </View>
      <View
        style={{
          height: 8,
          borderRadius: radii.full,
          backgroundColor: colors.surfaceElevated,
          overflow: 'hidden',
        }}
      >
        <View
          style={{
            height: '100%',
            width: `${pct}%`,
            borderRadius: radii.full,
            backgroundColor: pct >= 70 ? colors.success : pct >= 40 ? colors.warning : colors.destructive,
          }}
        />
      </View>
    </View>
  );
}
