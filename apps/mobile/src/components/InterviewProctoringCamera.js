import React, { forwardRef, useCallback, useImperativeHandle, useRef, useState } from 'react';
import { View, StyleSheet, Text } from 'react-native';
import { useCameraDevice, useVideoOutput } from 'react-native-vision-camera';
import { Camera as FaceDetectorCamera } from 'react-native-vision-camera-face-detector';
import { colors, radii, fontSize } from '../theme';

// Don't run face-status logic on every single detection callback (which can
// fire near camera frame-rate) — sample at most once per this interval.
const SAMPLE_INTERVAL_MS = 1200;
// A short, fixed-length clip starting at the violation moment. vision-camera
// v5's Recorder API has no rolling pre-buffer, so this is a deliberate,
// documented platform limitation vs. the web version's ability to keep a
// short look-back buffer — see final report.
const EVIDENCE_CLIP_SECONDS = 6;

/**
 * Front-camera preview + on-device (ML Kit, via
 * react-native-vision-camera-face-detector) face detection, throttled to
 * `SAMPLE_INTERVAL_MS`. Reports a stable status string via `onFaceStatus`:
 * 'ok' | 'no_face' | 'multiple_faces'. Also exposes `captureEvidenceClip()`
 * imperatively for a short (~6s) video clip to attach to a violation report.
 *
 * Uses react-native-vision-camera-face-detector's own drop-in `<Camera>`
 * (the library's "recommended way") rather than wiring a manual
 * `useFrameProcessor` + `react-native-worklets-core` worklet — it already
 * wraps vision-camera v5's output-composition API and hands back plain JS
 * callbacks, so this stays a single, simple worklets runtime
 * (Reanimated's `react-native-worklets`, already used app-wide) instead of
 * adding a second competing one just for this screen.
 */
const InterviewProctoringCamera = forwardRef(function InterviewProctoringCamera(
  { isActive, style, onFaceStatus, mirrored = true },
  ref
) {
  const device = useCameraDevice('front');
  const lastSampleRef = useRef(0);
  const [ready, setReady] = useState(false);

  // Video output used only for short evidence clips on a violation — no
  // audio track (mic permission/consent for proctoring evidence is scoped to
  // "can we see you", not "can we hear you"; voice answers are recorded
  // separately via expo-audio).
  const videoOutput = useVideoOutput({
    targetResolution: { width: 640, height: 480 },
    enableAudio: false,
    fileType: 'mp4',
  });

  const handleFacesDetected = useCallback(
    (faces) => {
      const now = Date.now();
      if (now - lastSampleRef.current < SAMPLE_INTERVAL_MS) return;
      lastSampleRef.current = now;
      const count = faces?.length || 0;
      const status = count === 0 ? 'no_face' : count > 1 ? 'multiple_faces' : 'ok';
      onFaceStatus?.(status);
    },
    [onFaceStatus]
  );

  const captureEvidenceClip = useCallback(async () => {
    try {
      const recorder = await videoOutput.createRecorder({ maxDuration: EVIDENCE_CLIP_SECONDS });
      const filePath = await new Promise((resolve, reject) => {
        recorder
          .startRecording(
            (path) => resolve(path),
            (err) => reject(err)
          )
          .catch(reject);
      });
      if (!filePath) return null;
      return {
        uri: filePath.startsWith('file://') ? filePath : `file://${filePath}`,
        name: 'violation-evidence.mp4',
        type: 'video/mp4',
      };
    } catch (e) {
      // Evidence capture is best-effort — the violation is still reported
      // without a clip rather than blocking the whole flow.
      return null;
    }
  }, [videoOutput]);

  useImperativeHandle(ref, () => ({ captureEvidenceClip }), [captureEvidenceClip]);

  if (!device) {
    return (
      <View style={[styles.fallback, style]} testID="proctoring-camera-unavailable">
        <Text style={styles.fallbackText}>No front camera</Text>
      </View>
    );
  }

  return (
    <View style={[styles.wrap, style]} testID="proctoring-camera">
      <FaceDetectorCamera
        style={StyleSheet.absoluteFill}
        device={device}
        isActive={isActive}
        mirrorMode={mirrored ? 'on' : 'off'}
        performanceMode="fast"
        runClassifications={false}
        runContours={false}
        runLandmarks={false}
        outputs={[videoOutput]}
        onFacesDetected={handleFacesDetected}
        onError={() => setReady(false)}
        onStarted={() => setReady(true)}
      />
      {!ready && (
        <View style={styles.loadingOverlay} pointerEvents="none">
          <Text style={styles.fallbackText}>Starting camera…</Text>
        </View>
      )}
    </View>
  );
});

export default InterviewProctoringCamera;

const styles = StyleSheet.create({
  wrap: {
    overflow: 'hidden',
    borderRadius: radii.md,
    backgroundColor: '#000',
  },
  fallback: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surfaceElevated,
    borderRadius: radii.md,
  },
  fallbackText: { color: colors.textMuted, fontSize: fontSize.xs },
  loadingOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#00000080',
  },
});
