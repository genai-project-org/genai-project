/**
 * Mock Interview API wrapper — thin functions over the shared `api` axios
 * instance (src/api.js), which already handles the `/api` base path, the
 * auth header, and 401 refresh. Mirrors the backend contract in
 * apps/api/routers/interview_routes.py and interview_pack_routes.py exactly
 * (read, not modified, as the backend is already built/tested).
 */
import api from '../api';

// ---- Entitlement / catalog ----

/**
 * Returns `{ sessions_remaining, grants: [{ grant_id, pack_slug, pack_name,
 * sessions_total, sessions_remaining, config: { technical_minutes,
 * behavioral_minutes, topics, seniority_levels, languages, sub_topics } }] }`.
 * Interviews are configurable per-pack (durations, allowed
 * topics/seniority/languages, optional behavioral round, optional
 * sub-topics) — `sessions_remaining` at the top level is the aggregate
 * across all owned grants; each grant has its own remaining count and its
 * own `config` that a session created against it must stay within.
 */
export function getEntitlement() {
  return api.get('/interview/entitlement').then((r) => r.data);
}

export function listInterviewPacks(currency = 'usd') {
  return api.get('/interview-packs/', { params: { currency } }).then((r) => r.data);
}

// ---- Sessions ----

/**
 * `grant_id` (required) picks which owned pack-grant to spend a session
 * from — every other field is validated server-side against that specific
 * grant's `config` (a 400 comes back with a plain-text reason if something's
 * out of bounds, e.g. a topic/seniority the grant doesn't allow).
 */
export function createSession({
  grant_id,
  topic,
  seniority = 'mid',
  sub_topic,
  language,
  include_behavioral,
  resume_profile_id,
}) {
  return api
    .post('/interview/sessions', {
      grant_id,
      topic,
      seniority,
      sub_topic,
      language,
      include_behavioral,
      resume_profile_id,
    })
    .then((r) => r.data);
}

export function listSessions(limit = 20) {
  return api.get('/interview/sessions', { params: { limit } }).then((r) => r.data);
}

export function getSessionStatus(sessionId) {
  return api.get(`/interview/sessions/${sessionId}/status`).then((r) => r.data);
}

export function endSession(sessionId) {
  return api.post(`/interview/sessions/${sessionId}/end`).then((r) => r.data);
}

export function getReport(sessionId) {
  return api.get(`/interview/sessions/${sessionId}/report`).then((r) => r.data);
}

/**
 * Submits one interview turn. `audio` (if provided) is a
 * `{ uri, name, type }` object as returned by expo-audio's recorder / our
 * InterviewProctoringCamera evidence capture — shaped for React Native's
 * FormData file convention (`{ uri, name, type }`, NOT a Blob).
 */
export function submitTurn(sessionId, { modality, text = '', audio = null }) {
  const form = new FormData();
  form.append('modality', modality);
  form.append('text', text);
  if (audio) {
    form.append('audio', {
      uri: audio.uri,
      name: audio.name || 'answer.m4a',
      type: audio.type || 'audio/m4a',
    });
  }
  return api
    .post(`/interview/sessions/${sessionId}/turn`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000, // STT + LLM + TTS server-side can genuinely take a while
    })
    .then((r) => r.data);
}

/**
 * Reports a proctoring violation. `type` must be one of the mobile-realistic
 * subset: "face_not_visible" | "multiple_faces" | "app_backgrounded".
 * `evidence` (optional) is a `{ uri, name, type }` short video clip.
 * The server is authoritative on warning_count/terminated — callers must
 * only update UI from this response, never optimistically.
 */
export function reportViolation(sessionId, { type, detectedAt, evidence = null }) {
  const form = new FormData();
  form.append('type', type);
  if (detectedAt) form.append('detected_at', detectedAt);
  if (evidence) {
    form.append('evidence', {
      uri: evidence.uri,
      name: evidence.name || 'evidence.mp4',
      type: evidence.type || 'video/mp4',
    });
  }
  return api
    .post(`/interview/sessions/${sessionId}/violations`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
}

// ---- Résumé profile (shared with Career Intelligence / Resume Intelligence) ----

export function getResumeProfile() {
  return api.get('/resume/profile').then((r) => r.data);
}

export function saveResumeProfileFile({ uri, name, mimeType }) {
  const form = new FormData();
  form.append('file', { uri, name: name || 'resume.pdf', type: mimeType || 'application/pdf' });
  return api
    .post('/resume/profile', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => r.data);
}

export function saveResumeProfileText(resumeText) {
  const form = new FormData();
  form.append('resume_text', resumeText);
  return api
    .post('/resume/profile', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => r.data);
}
