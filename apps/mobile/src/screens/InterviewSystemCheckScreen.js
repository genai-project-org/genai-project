import React, { useEffect, useRef, useState } from 'react';
import { View, Text, ScrollView, Linking, Platform } from 'react-native';
import { useDispatch } from 'react-redux';
import { useCameraPermission } from 'react-native-vision-camera';
import {
  useAudioRecorder,
  RecordingPresets,
  requestRecordingPermissionsAsync,
  getRecordingPermissionsAsync,
} from 'expo-audio';
import { Camera as CameraIcon, Mic, ShieldAlert } from 'lucide-react-native';
import { updateActiveSessionPhase } from '../store/slices/interviewSlice';
import InterviewProctoringCamera from '../components/InterviewProctoringCamera';
import ScreenHeader from '../components/ScreenHeader';
import { Card, Button } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';

// intro_camera -> intro_mic -> live_check -> consent -> (navigate to session)
const STEPS = ['intro_camera', 'intro_mic', 'live_check', 'consent'];

export default function InterviewSystemCheckScreen({ navigation, route }) {
  const { sessionId } = route.params || {};
  const dispatch = useDispatch();
  const [stepIdx, setStepIdx] = useState(0);
  const step = STEPS[stepIdx];

  const { hasPermission: hasCameraPermission, canRequestPermission: canRequestCamera, requestPermission: requestCameraPermission } =
    useCameraPermission();
  const [micStatus, setMicStatus] = useState(null); // 'granted' | 'denied' | 'undetermined'
  const [faceStatus, setFaceStatus] = useState('checking');
  const [micLevel, setMicLevel] = useState(0);

  const recorder = useAudioRecorder(
    { ...RecordingPresets.HIGH_QUALITY, isMeteringEnabled: true },
    (status) => {
      if (typeof status.metering === 'number') {
        // metering is dBFS, roughly -160 (silence) to 0 (max) — normalize to 0..1.
        setMicLevel(Math.max(0, Math.min(1, (status.metering + 60) / 60)));
      }
    }
  );
  const micCheckStarted = useRef(false);

  useEffect(() => {
    (async () => {
      const res = await getRecordingPermissionsAsync();
      setMicStatus(res.granted ? 'granted' : res.canAskAgain === false ? 'denied' : 'undetermined');
    })();
  }, []);

  useEffect(() => {
    if (step !== 'live_check' || micCheckStarted.current || micStatus !== 'granted') return;
    micCheckStarted.current = true;
    (async () => {
      try {
        await recorder.prepareToRecordAsync();
        recorder.record();
      } catch {
        // Non-fatal — the level meter simply stays flat.
      }
    })();
    return () => {
      if (recorder.isRecording) recorder.stop().catch(() => {});
    };
  }, [step, micStatus, recorder]);

  const goNext = () => setStepIdx((i) => Math.min(i + 1, STEPS.length - 1));

  const askCamera = async () => {
    const granted = await requestCameraPermission();
    if (granted) goNext();
  };

  const askMic = async () => {
    const res = await requestRecordingPermissionsAsync();
    setMicStatus(res.granted ? 'granted' : res.canAskAgain === false ? 'denied' : 'undetermined');
    if (res.granted) goNext();
  };

  const startInterview = () => {
    dispatch(updateActiveSessionPhase('live'));
    navigation.replace('InterviewSession', { sessionId });
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }} testID="interview-system-check-screen">
      <ScreenHeader title="System Check" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.lg }}>
        {step === 'intro_camera' && (
          <PermissionIntro
            Icon={CameraIcon}
            title="We need your camera"
            body="Your Mock Interview is proctored, like a real MAANG-style interview. We use your front camera on-device to confirm you're present throughout the session — video is never uploaded except a short clip if a violation is flagged."
            deniedHint={hasCameraPermission === false && !canRequestCamera}
            onContinue={hasCameraPermission ? goNext : askCamera}
            testID="camera-intro"
          />
        )}

        {step === 'intro_mic' && (
          <PermissionIntro
            Icon={Mic}
            title="We need your microphone"
            body="You'll answer out loud, like a real interview. We record short voice clips of your answers to transcribe and respond to — you can also type instead at any time."
            deniedHint={micStatus === 'denied'}
            onContinue={micStatus === 'granted' ? goNext : askMic}
            testID="mic-intro"
          />
        )}

        {step === 'live_check' && (
          <View style={{ gap: spacing.lg }}>
            <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600' }}>
              Let's check your camera and mic
            </Text>
            <InterviewProctoringCamera
              isActive
              style={{ width: '100%', height: 260 }}
              onFaceStatus={setFaceStatus}
            />
            <Card>
              <Text style={{ color: colors.text, fontWeight: '500' }}>
                {faceStatus === 'ok' && '✓ We can see your face clearly'}
                {faceStatus === 'no_face' && 'Please center your face in the frame'}
                {faceStatus === 'multiple_faces' && 'Only one person should be visible'}
                {faceStatus === 'checking' && 'Checking camera…'}
              </Text>
            </Card>
            <Card>
              <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginBottom: spacing.sm }}>
                Say a few words — you should see the bar move.
              </Text>
              <View style={{ height: 10, borderRadius: radii.full, backgroundColor: colors.surfaceElevated, overflow: 'hidden' }}>
                <View
                  style={{
                    height: '100%',
                    width: `${Math.round(micLevel * 100)}%`,
                    backgroundColor: colors.success,
                    borderRadius: radii.full,
                  }}
                />
              </View>
            </Card>
            <Button title="Continue" onPress={goNext} testID="system-check-continue" />
          </View>
        )}

        {step === 'consent' && (
          <View style={{ gap: spacing.lg }}>
            <Card style={{ borderColor: colors.warning, gap: spacing.sm, flexDirection: 'row' }}>
              <ShieldAlert color={colors.warning} size={22} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: colors.text, fontWeight: '600', marginBottom: 6 }}>
                  Proctoring policy — 2 warnings
                </Text>
                <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, lineHeight: 20 }}>
                  During your interview, we watch for your face going out of frame, more than one
                  person appearing on camera, and leaving the app — pressing the home button, opening
                  the notification shade or app switcher, or switching to another app all count as
                  leaving. Each of these gives you a warning. After 2 warnings, your interview ends
                  automatically and is scored on what was completed so far.
                </Text>
              </View>
            </Card>
            <Button title="I understand, start my interview" onPress={startInterview} testID="start-interview-btn" />
          </View>
        )}
      </ScrollView>
    </View>
  );
}

function PermissionIntro({ Icon, title, body, onContinue, deniedHint, testID }) {
  return (
    <Card style={{ gap: spacing.md }} testID={testID}>
      <View style={{ height: 48, width: 48, borderRadius: radii.md, backgroundColor: colors.primaryDim, alignItems: 'center', justifyContent: 'center' }}>
        <Icon color={colors.primary} size={24} />
      </View>
      <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600' }}>{title}</Text>
      <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, lineHeight: 20 }}>{body}</Text>
      {deniedHint ? (
        <View style={{ gap: spacing.sm }}>
          <Text style={{ color: colors.destructive, fontSize: fontSize.sm }}>
            {Platform.OS === 'ios'
              ? "Access was previously denied. iOS won't show the prompt again — enable it in Settings."
              : 'Access was previously denied. Enable it in Settings to continue.'}
          </Text>
          <Button
            title="Open Settings"
            variant="outline"
            onPress={() => Linking.openSettings()}
          />
        </View>
      ) : (
        <Button title="Continue" onPress={onContinue} testID={`${testID}-continue`} />
      )}
    </Card>
  );
}
