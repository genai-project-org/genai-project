import React, { useEffect, useRef } from 'react';
import { View, StyleSheet } from 'react-native';
import LottieView from 'lottie-react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  withSpring,
  Easing,
} from 'react-native-reanimated';
import { colors } from '../theme';

/**
 * AI interviewer avatar — a Lottie player driving a small state machine
 * (idle/listening/thinking/talking/nodding/warning), each a named 2s marker
 * segment inside assets/interview-avatar.json (see that file's generator
 * comment history for the per-state color/motion profile).
 *
 * `talkIntensity` (0-1) is layered on top of the Lottie loop as an extra
 * Reanimated scale/glow boost, driven by expo-audio's
 * `useAudioSampleListener` amplitude data during TTS playback in
 * InterviewSessionScreen. When amplitude sampling isn't available/supported,
 * callers simply leave `talkIntensity` at its default (0) and the avatar
 * still animates via the Lottie "talking" segment's own built-in loop —
 * a timed/looping fallback rather than true amplitude-driven motion.
 */
const GLOW_COLOR = {
  idle: colors.primary,
  listening: colors.success,
  thinking: '#8b5cf6',
  talking: colors.primary,
  nodding: colors.success,
  warning: colors.destructive,
};

export default function InterviewAvatar({ state = 'idle', talkIntensity = 0, size = 220, style }) {
  const lottieRef = useRef(null);
  const glow = useSharedValue(0.35);
  const boost = useSharedValue(0);

  useEffect(() => {
    lottieRef.current?.play(
      MARKER_RANGES[state]?.[0] ?? 0,
      MARKER_RANGES[state]?.[1] ?? 60
    );
  }, [state]);

  useEffect(() => {
    // Ambient pulse — subtler for idle/thinking, punchier for warning.
    const target = state === 'warning' ? 0.9 : state === 'talking' ? 0.7 : 0.4;
    const duration = state === 'warning' ? 260 : state === 'talking' ? 380 : 900;
    glow.value = withRepeat(
      withTiming(target, { duration, easing: Easing.inOut(Easing.ease) }),
      -1,
      true
    );
  }, [state, glow]);

  useEffect(() => {
    boost.value = withSpring(Math.max(0, Math.min(1, talkIntensity)), {
      damping: 8,
      stiffness: 120,
    });
  }, [talkIntensity, boost]);

  const glowStyle = useAnimatedStyle(() => ({
    opacity: glow.value,
    transform: [{ scale: 1 + boost.value * 0.12 }],
  }));

  const coreStyle = useAnimatedStyle(() => ({
    transform: [{ scale: 1 + boost.value * 0.08 }],
  }));

  const tint = GLOW_COLOR[state] || colors.primary;

  return (
    <View style={[styles.wrap, { width: size, height: size }, style]} testID="interview-avatar">
      <Animated.View
        pointerEvents="none"
        style={[
          styles.glow,
          { width: size, height: size, borderRadius: size / 2, backgroundColor: tint },
          glowStyle,
        ]}
      />
      <Animated.View style={[{ width: size, height: size }, coreStyle]}>
        <LottieView
          ref={lottieRef}
          source={require('../../assets/interview-avatar.json')}
          autoPlay
          loop
          style={{ width: size, height: size }}
        />
      </Animated.View>
    </View>
  );
}

// Mirrors assets/interview-avatar.json's `markers` (name -> [startFrame, endFrame]).
// LottieView.play(start, end) plays that inclusive frame range and (with
// `loop`) repeats it, giving each state its own self-contained animation.
const MARKER_RANGES = {
  idle: [0, 60],
  listening: [60, 120],
  thinking: [120, 180],
  talking: [180, 240],
  nodding: [240, 300],
  warning: [300, 360],
};

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', justifyContent: 'center' },
  glow: { position: 'absolute' },
});
