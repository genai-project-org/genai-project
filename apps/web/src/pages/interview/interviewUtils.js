// Shared helpers for the Mock Interview pages — same flattening trick used in
// Practice.jsx/Contest.jsx/Resume.jsx (FastAPI's 402/409/429 responses carry
// structured `detail` objects, everything else a plain string), plus the
// blob-download pattern from Contest.jsx's certificate/stats-card buttons.
import api from '@/lib/api';

export function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

export async function downloadBlob(path, filename) {
  const { data } = await api.get(path, { responseType: 'blob' });
  const blobUrl = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(blobUrl);
}

export const TOPIC_META = {
  dsa: { label: 'DSA', desc: 'Data structures & algorithms in a live code editor.' },
  hld: { label: 'HLD', desc: 'High-level system design — architecture, trade-offs, scale.' },
  lld: { label: 'LLD', desc: 'Low-level / object-oriented design — classes, interfaces, patterns.' },
  design: { label: 'Product Design', desc: 'Product sense & design thinking discussion.' },
  hr: { label: 'HR / Behavioral', desc: 'Behavioral & culture-fit round.' },
};

// Seniority levels and languages are now pack-defined (InterviewPackConfig on
// the backend) rather than a fixed enum, so these are label LOOKUPS with a
// humanized fallback for any value a pack's config carries that isn't in the
// common set below — never a hard-coded list of options to render.
export const SENIORITY_LABEL = {
  entry: 'Entry level',
  mid: 'Mid level',
  senior: 'Senior',
};

export const LANGUAGE_LABEL = {
  python: 'Python',
  javascript: 'JavaScript',
  cpp: 'C++',
  java: 'Java',
};

export const MONACO_LANGUAGE = {
  python: 'python', javascript: 'javascript', cpp: 'cpp', java: 'java',
};

export function humanize(value) {
  if (!value) return '';
  return value.split(/[_-]/g).map((w) => w[0]?.toUpperCase() + w.slice(1)).join(' ');
}

// A short "what's in this pack" line for pack-picker cards (Home's paywall
// cards and the setup wizard's grant-picker step), built from the
// server-provided config rather than any hard-coded per-pack copy.
export function summarizePackConfig(config) {
  if (!config) return '';
  const duration = config.behavioral_minutes > 0
    ? `${config.technical_minutes}+${config.behavioral_minutes} min`
    : `${config.technical_minutes} min · technical only`;
  const topics = config.topics || [];
  const topicsPart = topics.length >= 5 ? 'All topics' : topics.map((t) => TOPIC_META[t]?.label || t).join('/');
  return `${duration} · ${topicsPart}`;
}

// Mirrors apps/api/services/interview_service.py's MIN/MAX_*_MINUTES —
// duration is candidate-adjustable to fit their schedule, bounded globally
// regardless of which pack they're spending (packs still gate topics,
// languages, seniority and whether a behavioral round exists at all).
export const MIN_TECHNICAL_MINUTES = 15;
export const MAX_TECHNICAL_MINUTES = 90;
export const MIN_BEHAVIORAL_MINUTES = 5;
export const MAX_BEHAVIORAL_MINUTES = 30;

export const ACTIVE_STATUSES = ['created', 'technical_in_progress', 'behavioral_in_progress'];

export const STATUS_LABEL = {
  created: 'Starting',
  technical_in_progress: 'Technical round',
  behavioral_in_progress: 'Behavioral round',
  completed: 'Completed',
  terminated_violations: 'Ended — proctoring',
  terminated_error: 'Ended — error',
  abandoned: 'Abandoned',
  expired: 'Expired',
};

export function fmtClock(minutes) {
  const total = Math.max(0, Math.round((minutes || 0) * 60));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export const DIMENSION_ORDER = [
  'communication', 'technical_correctness', 'problem_solving', 'confidence', 'proctoring_integrity',
];

export const DIMENSION_LABEL = {
  communication: 'Communication',
  technical_correctness: 'Technical Correctness',
  problem_solving: 'Problem Solving',
  confidence: 'Confidence',
  proctoring_integrity: 'Proctoring Integrity',
};

export const VIOLATION_LABEL = {
  face_not_visible: 'Face not visible',
  multiple_faces: 'Another person detected in frame',
  tab_blur: 'Switched away from the interview tab',
  fullscreen_exit: 'Exited fullscreen',
  copy_paste: 'Copy/paste attempted',
  devtools_suspected: 'Developer tools suspected open',
};
