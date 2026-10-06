import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  FlatList,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  Alert,
  AppState,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { useDispatch } from 'react-redux';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  withSequence,
} from 'react-native-reanimated';
import { Mic, Square, Send, LogOut } from 'lucide-react-native';
import * as FileSystem from 'expo-file-system';
import {
  useAudioRecorder,
  RecordingPresets,
  createAudioPlayer,
  useAudioPlayerStatus,
  useAudioSampleListener,
} from 'expo-audio';
import {
  getSessionStatus,
  submitTurn,
  endSession,
  reportViolation,
} from '../services/interviewApi';
import { setWarningCount, clearActiveSession } from '../store/slices/interviewSlice';
import InterviewAvatar from '../components/InterviewAvatar';
import InterviewProctoringCamera from '../components/InterviewProctoringCamera';
import { colors, spacing, fontSize, radii } from '../theme';

const STATUS_POLL_MS = 4000;
// Consecutive bad face-status samples (each ~1.2s apart, see
// InterviewProctoringCamera's own throttle) before we treat it as a real,
// sustained problem rather than a blink/head-turn.
const FACE_VIOLATION_STREAK = 3;
// How long a backgrounding has to persist before it counts as a violation —
// long enough that a quick permission re-prompt or an incoming-call dismissal
// doesn't false-positive.
const BACKGROUND_DEBOUNCE_MS = 2000;
const VIOLATION_COOLDOWN_MS = 20000;

export default function InterviewSessionScreen({ navigation, route }) {
  const { sessionId } = route.params || {};
  const insets = useSafeAreaInsets();
  const dispatch = useDispatch();

  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [avatarState, setAvatarState] = useState('idle');
  const [talkIntensity, setTalkIntensity] = useState(0);
  const [round, setRound] = useState('technical');
  const [minutesRemaining, setMinutesRemaining] = useState(null);
  const [busy, setBusy] = useState(false); // awaiting a turn response
  const [isRecording, setIsRecording] = useState(false);
  const [terminated, setTerminated] = useState(false);
  const [warningBanner, setWarningBanner] = useState(null);

  const [activePlayer, setActivePlayer] = useState(null);
  const listRef = useRef(null);
  const cameraRef = useRef(null);
  const faceBadStreakRef = useRef(0);
  const lastViolationAtRef = useRef({});
  const bgTimerRef = useRef(null);
  const pollRef = useRef(null);
  const endedRef = useRef(false);
  const lastRoundRef = useRef('technical');

  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

  const borderPulse = useSharedValue(0);
  const interstitial = useSharedValue(0);

  // ---- Disable the drawer swipe while a live session is on screen, so an
  // accidental drawer-open gesture is never mistaken for "leaving the app". ----
  useFocusEffect(
    useCallback(() => {
      navigation.getParent()?.setOptions({ swipeEnabled: false });
      return () => navigation.getParent()?.setOptions({ swipeEnabled: true });
    }, [navigation])
  );

  const appendMessage = useCallback((msg) => {
    setMessages((m) => [...m, msg]);
    setTimeout(() => listRef.current?.scrollToEnd?.({ animated: true }), 50);
  }, []);

  const applyViolationResult = useCallback(
    (result) => {
      dispatch(setWarningCount(result.warning_count));
      if (result.terminated) {
        endedRef.current = true;
        setTerminated(true);
        return;
      }
      if (result.warning_count === 1) {
        setAvatarState('warning');
        borderPulse.value = withSequence(withTiming(1, { duration: 200 }), withTiming(0, { duration: 800 }));
        setWarningBanner(`Warning 1 of 2 — ${result.warnings_remaining} more ends your interview.`);
        setTimeout(() => setWarningBanner(null), 5000);
      } else if (result.warning_count >= 2) {
        setAvatarState('warning');
        borderPulse.value = withRepeat(withSequence(withTiming(1, { duration: 200 }), withTiming(0.2, { duration: 200 })), 4, true);
        Alert.alert(
          'Final warning',
          'This is your final warning. One more violation will end your interview.',
          [{ text: 'Understood' }]
        );
      }
    },
    [dispatch, borderPulse]
  );

  const fireViolation = useCallback(
    async (type) => {
      if (endedRef.current) return;
      const now = Date.now();
      const last = lastViolationAtRef.current[type] || 0;
      if (now - last < VIOLATION_COOLDOWN_MS) return;
      lastViolationAtRef.current[type] = now;
      try {
        const evidence = await cameraRef.current?.captureEvidenceClip?.();
        const result = await reportViolation(sessionId, {
          type,
          detectedAt: new Date().toISOString(),
          evidence,
        });
        applyViolationResult(result);
      } catch {
        // Violation reporting is best-effort from the client's point of
        // view — the server remains the source of truth either way.
      }
    },
    [sessionId, applyViolationResult]
  );

  const handleFaceStatus = useCallback(
    (status) => {
      if (status === 'ok') {
        faceBadStreakRef.current = 0;
        return;
      }
      faceBadStreakRef.current += 1;
      if (faceBadStreakRef.current >= FACE_VIOLATION_STREAK) {
        faceBadStreakRef.current = 0;
        fireViolation(status);
      }
    },
    [fireViolation]
  );

  // ---- AppState backgrounding, debounced ----
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'background' || next === 'inactive') {
        if (bgTimerRef.current) clearTimeout(bgTimerRef.current);
        bgTimerRef.current = setTimeout(() => {
          fireViolation('app_backgrounded');
        }, BACKGROUND_DEBOUNCE_MS);
      } else if (next === 'active') {
        if (bgTimerRef.current) {
          clearTimeout(bgTimerRef.current);
          bgTimerRef.current = null;
        }
      }
    });
    return () => {
      sub.remove();
      if (bgTimerRef.current) clearTimeout(bgTimerRef.current);
    };
  }, [fireViolation]);

  // Release the native player when it's replaced or the screen unmounts.
  useEffect(() => () => activePlayer?.remove?.(), [activePlayer]);

  // ---- Status polling ----
  useEffect(() => {
    if (!sessionId) return undefined;
    const poll = async () => {
      try {
        const status = await getSessionStatus(sessionId);
        if (endedRef.current) return;
        setMinutesRemaining(status.minutes_remaining);
        dispatch(setWarningCount(status.warning_count));
        if (status.round && status.round !== lastRoundRef.current) {
          lastRoundRef.current = status.round;
          setRound(status.round);
          interstitial.value = withSequence(withTiming(1, { duration: 400 }), withTiming(0, { duration: 400 }));
        }
        if (
          status.session_status &&
          !['created', 'technical_in_progress', 'behavioral_in_progress'].includes(status.session_status)
        ) {
          endedRef.current = true;
          if (status.session_status === 'terminated_violations') {
            setTerminated(true);
          } else {
            dispatch(clearActiveSession());
            navigation.replace('InterviewReport', { sessionId });
          }
        }
      } catch {
        // Transient network hiccups shouldn't crash a live session.
      }
    };
    poll();
    pollRef.current = setInterval(poll, STATUS_POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [sessionId, dispatch, navigation, interstitial]);

  // ---- Turn submission ----
  const playInterviewerAudio = useCallback(
    async (base64) => {
      if (!base64) return;
      try {
        const path = `${FileSystem.cacheDirectory}interview-tts-${Date.now()}.wav`;
        await FileSystem.writeAsStringAsync(path, base64, { encoding: FileSystem.EncodingType.Base64 });
        const player = createAudioPlayer(path);
        setActivePlayer(player);
        setAvatarState('talking');
        player.play();
      } catch {
        // Playback is a nice-to-have — the interviewer's text is always shown.
        setAvatarState('nodding');
        setTimeout(() => setAvatarState('listening'), 1200);
      }
    },
    []
  );

  const sendTurn = useCallback(
    async ({ modality, text = '', audio = null }) => {
      if (busy || endedRef.current) return;
      if (modality === 'text') {
        appendMessage({ id: `u${Date.now()}`, role: 'candidate', text });
      }
      setBusy(true);
      setAvatarState('thinking');
      try {
        const result = await submitTurn(sessionId, { modality, text, audio });
        if (result.transcript && modality !== 'text') {
          appendMessage({ id: `u${Date.now()}`, role: 'candidate', text: result.transcript });
        }
        if (result.interviewer_text) {
          appendMessage({ id: `a${Date.now()}`, role: 'interviewer', text: result.interviewer_text });
        }
        setMinutesRemaining(result.minutes_remaining);
        if (result.round) {
          setRound(result.round);
          lastRoundRef.current = result.round;
        }
        dispatch(setWarningCount(result.warning_count));
        if (result.interviewer_audio_base64) {
          await playInterviewerAudio(result.interviewer_audio_base64);
        } else {
          setAvatarState('nodding');
          setTimeout(() => setAvatarState('listening'), 1200);
        }
        if (
          result.session_status &&
          !['created', 'technical_in_progress', 'behavioral_in_progress'].includes(result.session_status)
        ) {
          endedRef.current = true;
          dispatch(clearActiveSession());
          navigation.replace('InterviewReport', { sessionId });
        }
      } catch (err) {
        Alert.alert('Turn failed', err.response?.data?.detail || 'Please try again.');
        setAvatarState('listening');
      } finally {
        setBusy(false);
      }
    },
    [busy, sessionId, appendMessage, dispatch, navigation, playInterviewerAudio]
  );

  const submitText = () => {
    const text = inputText.trim();
    if (!text) return;
    setInputText('');
    sendTurn({ modality: 'text', text });
  };

  const toggleRecording = async () => {
    if (busy) return;
    if (isRecording) {
      setIsRecording(false);
      try {
        await recorder.stop();
        setAvatarState('thinking');
        sendTurn({ modality: 'voice', audio: recorder.uri ? { uri: recorder.uri, name: 'answer.m4a', type: 'audio/m4a' } : null });
      } catch {
        setAvatarState('listening');
      }
      return;
    }
    try {
      await recorder.prepareToRecordAsync();
      recorder.record();
      setIsRecording(true);
      setAvatarState('listening');
    } catch {
      Alert.alert('Microphone unavailable', 'Could not start recording. You can type your answer instead.');
    }
  };

  const confirmEnd = () => {
    Alert.alert('End interview?', 'Your session will be scored on what you completed so far.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'End Interview',
        style: 'destructive',
        onPress: async () => {
          endedRef.current = true;
          try {
            await endSession(sessionId);
          } catch {
            // Report screen will still poll/resolve status server-side.
          }
          dispatch(clearActiveSession());
          navigation.replace('InterviewReport', { sessionId });
        },
      },
    ]);
  };

  const borderStyle = useAnimatedStyle(() => ({
    borderColor: borderPulse.value > 0 ? colors.destructive : 'transparent',
    borderWidth: borderPulse.value > 0 ? 3 : 0,
  }));
  const interstitialStyle = useAnimatedStyle(() => ({
    opacity: interstitial.value,
  }));

  if (terminated) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, alignItems: 'center', justifyContent: 'center', padding: spacing.xl }}>
        <Text style={{ color: colors.destructive, fontSize: fontSize.xxl, fontWeight: '700', textAlign: 'center' }}>
          Interview ended
        </Text>
        <Text style={{ color: colors.textMuted, fontSize: fontSize.md, textAlign: 'center', marginTop: spacing.md }}>
          Your interview was ended after repeated proctoring warnings. You'll still get a report based
          on what was completed.
        </Text>
        <TouchableOpacity
          onPress={() => navigation.replace('InterviewReport', { sessionId })}
          style={{ marginTop: spacing.xl, backgroundColor: colors.primary, borderRadius: radii.md, paddingHorizontal: spacing.xl, paddingVertical: 14 }}
        >
          <Text style={{ color: '#fff', fontWeight: '600' }}>View report</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={{ flex: 1, backgroundColor: colors.bg }}
      testID="interview-session-screen"
    >
      <Animated.View style={[{ flex: 1 }, borderStyle]}>
        <View style={{ paddingTop: insets.top, paddingHorizontal: spacing.md, paddingBottom: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text style={{ color: colors.text, fontWeight: '600', textTransform: 'uppercase', fontSize: fontSize.sm }}>
            {round === 'behavioral' ? 'Behavioral' : 'Technical'} round
          </Text>
          <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
            {minutesRemaining != null ? `${Math.max(0, Math.round(minutesRemaining))} min left` : ''}
          </Text>
          <TouchableOpacity onPress={confirmEnd} style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
            <LogOut color={colors.destructive} size={16} />
            <Text style={{ color: colors.destructive, fontSize: fontSize.sm }}>End</Text>
          </TouchableOpacity>
        </View>

        {!!warningBanner && (
          <View style={{ backgroundColor: colors.warning + '30', borderColor: colors.warning, borderWidth: 1, marginHorizontal: spacing.md, borderRadius: radii.md, padding: spacing.sm }}>
            <Text style={{ color: colors.warning, fontSize: fontSize.sm, fontWeight: '600' }}>{warningBanner}</Text>
          </View>
        )}

        <View style={{ height: '42%', alignItems: 'center', justifyContent: 'center' }}>
          <InterviewAvatar state={avatarState} talkIntensity={talkIntensity} />
          {activePlayer && (
            <PlaybackAmplitudeBridge
              player={activePlayer}
              onIntensity={setTalkIntensity}
              onDone={() => setAvatarState('listening')}
            />
          )}
          <View style={{ position: 'absolute', top: 8, right: spacing.md, width: 90, height: 120 }}>
            <InterviewProctoringCamera
              ref={cameraRef}
              isActive
              style={{ width: 90, height: 120 }}
              onFaceStatus={handleFaceStatus}
            />
          </View>
          <Animated.View pointerEvents="none" style={[{ position: 'absolute', alignItems: 'center' }, interstitialStyle]}>
            <Text style={{ color: colors.primary, fontWeight: '700', fontSize: fontSize.lg }}>
              Moving to the {round === 'behavioral' ? 'behavioral' : 'technical'} round
            </Text>
          </Animated.View>
        </View>

        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(m) => m.id}
          style={{ flex: 1 }}
          contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
          renderItem={({ item }) => <TurnBubble message={item} />}
          ListFooterComponent={busy ? <ThinkingIndicator /> : null}
        />

        <View style={{ borderTopWidth: 1, borderColor: colors.border, padding: spacing.md, paddingBottom: Math.max(insets.bottom, spacing.md), flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <TextInput
            value={inputText}
            onChangeText={setInputText}
            placeholder="Type your answer..."
            placeholderTextColor={colors.textDim}
            multiline
            editable={!busy}
            style={{ flex: 1, maxHeight: 100, borderWidth: 1, borderColor: colors.border, borderRadius: radii.md, backgroundColor: colors.card, color: colors.text, paddingHorizontal: 14, paddingVertical: 10 }}
            testID="interview-text-input"
          />
          {inputText.trim() ? (
            <TouchableOpacity onPress={submitText} disabled={busy} style={{ padding: 12, borderRadius: radii.md, backgroundColor: colors.primary }}>
              <Send color="#fff" size={18} />
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              onPress={toggleRecording}
              disabled={busy}
              testID="interview-mic-fab"
              style={{
                height: 52, width: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center',
                backgroundColor: isRecording ? colors.destructive : colors.primary,
              }}
            >
              {isRecording ? <Square color="#fff" size={20} fill="#fff" /> : <Mic color="#fff" size={22} />}
            </TouchableOpacity>
          )}
        </View>
      </Animated.View>
    </KeyboardAvoidingView>
  );
}

/**
 * Bridges expo-audio's amplitude sampling of the currently-playing
 * interviewer TTS clip to the avatar's `talkIntensity` prop. Only mounted
 * while a real player exists (see InterviewSessionScreen's `activePlayer`
 * state), so it never needs a dummy/fallback player just to satisfy the
 * rules of hooks. If amplitude sampling isn't supported on this
 * platform/build, `useAudioSampleListener`'s callback simply never fires and
 * `talkIntensity` stays at 0 — the avatar still animates via its own
 * "talking" Lottie loop (see InterviewAvatar's doc comment), which is the
 * timed/looping fallback the task spec calls for.
 */
function PlaybackAmplitudeBridge({ player, onIntensity, onDone }) {
  const status = useAudioPlayerStatus(player);
  useAudioSampleListener(player, (sample) => {
    const frames = sample?.channels?.[0]?.frames || [];
    if (!frames.length) return;
    const peak = frames.reduce((m, v) => Math.max(m, Math.abs(v)), 0);
    onIntensity(Math.min(1, peak * 3));
  });

  useEffect(() => {
    if (status && !status.playing && status.currentTime > 0) {
      onIntensity(0);
      onDone();
    }
  }, [status, onIntensity, onDone]);

  return null;
}

function ThinkingIndicator() {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, paddingLeft: 4 }}>
      <ActivityIndicator size="small" color={colors.primary} />
      <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>Transcribing / thinking…</Text>
    </View>
  );
}

function TurnBubble({ message }) {
  const isCandidate = message.role === 'candidate';
  return (
    <View style={{ flexDirection: 'row', justifyContent: isCandidate ? 'flex-end' : 'flex-start' }}>
      <View
        style={{
          maxWidth: '85%',
          borderRadius: 14,
          padding: 12,
          ...(isCandidate
            ? { backgroundColor: colors.primaryDim, borderWidth: 1, borderColor: colors.primary + '40', borderTopRightRadius: 4 }
            : { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderTopLeftRadius: 4 }),
        }}
      >
        <Text style={{ color: colors.text, fontSize: fontSize.md, lineHeight: 20 }}>{message.text}</Text>
      </View>
    </View>
  );
}
