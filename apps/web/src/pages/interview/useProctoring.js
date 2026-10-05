import { useEffect, useRef } from 'react';
import * as faceapi from 'face-api.js';
import * as tf from '@tensorflow/tfjs';
import * as cocoSsd from '@tensorflow-models/coco-ssd';
import api from '@/lib/api';

// Model weights live in apps/web/public/models — tiny_face_detector (face
// presence/orientation) AND coco-ssd (general person/body detection), both
// vendored locally rather than fetched from a CDN at interview-time, same
// self-hosted-no-recurring-cost posture as the rest of this feature's speech
// stack. If either is missing (e.g. a deploy that forgot to copy /models),
// loading fails gracefully and just disables that check — the other
// proctoring signals (tab-focus/fullscreen/copy-paste) keep working.
const MODEL_URL = '/models';
const COCO_SSD_MODEL_URL = '/models/coco-ssd/model.json';
const SAMPLE_INTERVAL_MS = 1000;
const NO_FACE_STREAK_THRESHOLD = 4;        // ~4s of no face before flagging
const PERSON_SCORE_THRESHOLD = 0.55;       // coco-ssd confidence floor for a "person" box
const VIOLATION_COOLDOWN_MS = 6000;        // don't re-report the same type back-to-back
const BUFFER_SECONDS = 8;                  // rolling evidence-clip window
const CHUNK_MS = 1000;
const DEVTOOLS_CHECK_INTERVAL_MS = 2000;
const DEVTOOLS_SIZE_THRESHOLD = 160;       // px gap between outer/inner window size

/**
 * Owns all client-side proctoring detection for a live interview session and
 * reports confirmed violations to the server, which is the sole source of
 * truth on warning counts / termination (see interview_routes.py). The
 * caller only finds out about a warning/termination via `onResult`, fired
 * AFTER the server responds — never optimistically.
 *
 * `stream` is the SAME getUserMedia stream already used for the self-camera
 * PIP — this hook does not open a second one. `videoEl` is a ref to the
 * <video> element playing that stream, used as the face-api detection input.
 */
export default function useProctoring({ sessionId, stream, videoEl, enabled, onResult, onError }) {
  const modelsReadyRef = useRef(false);
  const noFaceStreakRef = useRef(0);
  const lastViolationAtRef = useRef({});
  const stoppedRef = useRef(false);
  const bufferRef = useRef([]); // [{ blob, ts }]

  const reportedTerminatedRef = useRef(false);

  useEffect(() => {
    stoppedRef.current = false;
    reportedTerminatedRef.current = false;
  }, [sessionId]);

  // ---- Report a confirmed violation to the server -------------------------
  const reportViolation = async (type) => {
    if (stoppedRef.current || !enabled) return;
    const now = Date.now();
    const last = lastViolationAtRef.current[type] || 0;
    if (now - last < VIOLATION_COOLDOWN_MS) return;
    lastViolationAtRef.current[type] = now;

    try {
      const form = new FormData();
      form.append('type', type);
      form.append('detected_at', new Date().toISOString());
      const clip = buildEvidenceClip();
      if (clip) form.append('evidence', clip, `${type}.webm`);
      const { data } = await api.post(`/interview/sessions/${sessionId}/violations`, form);
      if (data.terminated) {
        stoppedRef.current = true;
        if (!reportedTerminatedRef.current) {
          reportedTerminatedRef.current = true;
          onResult?.({ ...data, type });
        }
      } else {
        onResult?.({ ...data, type });
      }
    } catch (e) {
      onError?.(e);
    }
  };

  const buildEvidenceClip = () => {
    const chunks = bufferRef.current.map((c) => c.blob);
    if (!chunks.length) return null;
    try {
      return new Blob(chunks, { type: 'video/webm' });
    } catch {
      return null;
    }
  };

  // ---- Rolling evidence-clip recorder (video track only) -------------------
  useEffect(() => {
    if (!enabled || !stream) return undefined;
    const videoTracks = stream.getVideoTracks();
    if (!videoTracks.length || typeof MediaRecorder === 'undefined') return undefined;

    let recorder;
    try {
      const evidenceStream = new MediaStream(videoTracks);
      recorder = new MediaRecorder(evidenceStream, { mimeType: 'video/webm;codecs=vp8' });
    } catch {
      return undefined;
    }

    recorder.ondataavailable = (e) => {
      if (!e.data || e.data.size === 0) return;
      const now = Date.now();
      bufferRef.current = [...bufferRef.current, { blob: e.data, ts: now }].filter(
        (c) => now - c.ts <= BUFFER_SECONDS * 1000,
      );
    };
    try { recorder.start(CHUNK_MS); } catch { /* ignore — evidence is best-effort */ }

    return () => {
      try { if (recorder.state !== 'inactive') recorder.stop(); } catch { /* noop */ }
    };
  }, [enabled, stream]);

  // ---- Presence sampling: face orientation (TinyFaceDetector) + general
  // person/body detection (coco-ssd) run on the SAME tick against the SAME
  // video frame, so the two signals can't disagree about what was on-camera
  // a moment apart from each other.
  //
  // Why two models instead of just face-api: face-api's face detector only
  // fires on a reasonably frontal, unobstructed face — a second person who
  // has only their body/shoulder/back of head in frame (not looking at the
  // camera) never registers as a "face" at all, so the old "multiple_faces"
  // check (face count > 1) missed exactly that case. coco-ssd's 'person'
  // class detects a human BODY regardless of facing direction, so a second
  // person is flagged the moment any part of them is in frame — not only
  // once their face happens to turn toward the camera.
  const cocoModelRef = useRef(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    let intervalId;

    (async () => {
      if (!modelsReadyRef.current) {
        try {
          await faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL);
          modelsReadyRef.current = true;
        } catch (e) {
          onError?.(e);
          // degrade silently — other proctoring checks still run
        }
      }
      if (!cocoModelRef.current) {
        try {
          await tf.ready();
          cocoModelRef.current = await cocoSsd.load({ modelUrl: COCO_SSD_MODEL_URL });
        } catch (e) {
          onError?.(e); // degrade silently — face-only presence checks still run
        }
      }
      if (cancelled) return;

      intervalId = setInterval(async () => {
        const video = videoEl?.current;
        if (!video || video.readyState < 2 || stoppedRef.current) return;

        if (cocoModelRef.current) {
          try {
            const objects = await cocoModelRef.current.detect(video, 10, PERSON_SCORE_THRESHOLD);
            const personCount = objects.filter((o) => o.class === 'person').length;
            if (personCount > 1) reportViolation('multiple_faces');
          } catch {
            // a single failed detection frame isn't worth surfacing
          }
        }

        if (modelsReadyRef.current) {
          try {
            const detections = await faceapi.detectAllFaces(
              video,
              new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 }),
            );
            if (detections.length === 0) {
              noFaceStreakRef.current += 1;
              if (noFaceStreakRef.current >= NO_FACE_STREAK_THRESHOLD) {
                noFaceStreakRef.current = 0;
                reportViolation('face_not_visible');
              }
            } else {
              noFaceStreakRef.current = 0;
            }
          } catch {
            // a single failed detection frame isn't worth surfacing
          }
        }
      }, SAMPLE_INTERVAL_MS);
    })();

    return () => { cancelled = true; if (intervalId) clearInterval(intervalId); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sessionId]);

  // ---- Tab focus / visibility ----------------------------------------------
  useEffect(() => {
    if (!enabled) return undefined;
    const onBlurOrHide = () => reportViolation('tab_blur');
    document.addEventListener('visibilitychange', () => { if (document.hidden) onBlurOrHide(); });
    window.addEventListener('blur', onBlurOrHide);
    return () => {
      document.removeEventListener('visibilitychange', onBlurOrHide);
      window.removeEventListener('blur', onBlurOrHide);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sessionId]);

  // ---- Fullscreen ------------------------------------------------------------
  useEffect(() => {
    if (!enabled) return undefined;
    const onFsChange = () => {
      if (!document.fullscreenElement && !stoppedRef.current) reportViolation('fullscreen_exit');
    };
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sessionId]);

  // ---- Copy / paste blockers -------------------------------------------------
  useEffect(() => {
    if (!enabled) return undefined;
    const blockContextMenu = (e) => e.preventDefault();
    const onCopy = (e) => { e.preventDefault(); reportViolation('copy_paste'); };
    const onPaste = (e) => { e.preventDefault(); reportViolation('copy_paste'); };
    document.addEventListener('contextmenu', blockContextMenu);
    document.addEventListener('copy', onCopy);
    document.addEventListener('paste', onPaste);
    return () => {
      document.removeEventListener('contextmenu', blockContextMenu);
      document.removeEventListener('copy', onCopy);
      document.removeEventListener('paste', onPaste);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sessionId]);

  // ---- Devtools heuristic (best-effort, not in the primary spec list) --------
  useEffect(() => {
    if (!enabled) return undefined;
    const check = () => {
      const widthGap = window.outerWidth - window.innerWidth;
      const heightGap = window.outerHeight - window.innerHeight;
      if (widthGap > DEVTOOLS_SIZE_THRESHOLD || heightGap > DEVTOOLS_SIZE_THRESHOLD) {
        reportViolation('devtools_suspected');
      }
    };
    const id = setInterval(check, DEVTOOLS_CHECK_INTERVAL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sessionId]);

  return { stop: () => { stoppedRef.current = true; } };
}
