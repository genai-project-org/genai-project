import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, AlertTriangle, Ear, Brain, User } from 'lucide-react';

import marcusSteele from '@/assets/interviewers/marcus-steele.jpg';
import naomiReyes from '@/assets/interviewers/naomi-reyes.jpg';
import adrianCole from '@/assets/interviewers/adrian-cole.jpg';
import sophiaLang from '@/assets/interviewers/sophia-lang.jpg';
import tariqFarouk from '@/assets/interviewers/tariq-farouk.jpg';

// The 5 interviewer personas a candidate can be assigned — must mirror
// services/interview_service.py's INTERVIEWERS list id-for-id (that's the
// source of truth for which id the backend actually sends back; this map
// only supplies the photo asset for each one). Photorealistic but SYNTHETIC
// portraits (StyleGAN2-generated) — no real, identifiable person behind any
// of them, chosen after the earlier illustrated-avatar pass read as too
// cartoonish for a serious interview.
export const INTERVIEWER_PHOTOS = {
  'marcus-steele': marcusSteele,
  'naomi-reyes': naomiReyes,
  'adrian-cole': adrianCole,
  'sophia-lang': sophiaLang,
  'tariq-farouk': tariqFarouk,
};

// Per-state visual language: a glow-ring color/intensity plus a scale/rotate
// motion on the avatar itself.
const STATE_STYLE = {
  idle: { glow: 'hsl(258 90% 66% / 0.3)', ring: 'border-primary/30' },
  listening: { glow: 'hsl(199 89% 60% / 0.4)', ring: 'border-sky-400/40' },
  thinking: { glow: 'hsl(38 92% 60% / 0.4)', ring: 'border-amber-400/40' },
  talking: { glow: 'hsl(152 76% 55% / 0.5)', ring: 'border-emerald-400/50' },
  nodding: { glow: 'hsl(152 76% 55% / 0.5)', ring: 'border-emerald-400/50' },
  warning: { glow: 'hsl(0 84% 60% / 0.55)', ring: 'border-rose-500/60' },
};

/**
 * The always-visible AI-interviewer avatar. `interviewer` is the
 * `{id, name}` object the backend assigns per session (see
 * interview_service.get_interviewer_public) — the SAME interviewer's photo
 * for the whole session, never re-randomized on re-render. `state` drives
 * idle/listening/thinking/talking/nodding/warning; `amplitude` (0-1) is the
 * live playback amplitude of `interviewer_audio_base64`, read in the parent,
 * and pushes the "talking" motion harder on louder syllables.
 */
export default function AvatarStage({ state = 'idle', amplitude = 0, interviewer }) {
  const style = STATE_STYLE[state] || STATE_STYLE.idle;
  const photo = interviewer?.id ? INTERVIEWER_PHOTOS[interviewer.id] : null;

  const talkScale = state === 'talking' ? 1 + Math.min(0.05, amplitude * 0.05) : 1;
  const talkBob = state === 'talking' ? -Math.min(4, amplitude * 4) : 0;

  return (
    <div className="relative flex flex-col items-center justify-center gap-3 select-none" data-testid="interview-avatar">
      <motion.div
        className={`relative h-56 w-56 rounded-full border-2 ${style.ring} overflow-hidden bg-muted flex items-center justify-center`}
        animate={{
          boxShadow: [`0 0 30px 6px ${style.glow}`, `0 0 55px 14px ${style.glow}`, `0 0 30px 6px ${style.glow}`],
          scale: state === 'warning' ? [1, 1.04, 1] : talkScale,
          y: talkBob,
          rotate: state === 'nodding' ? [0, -3, 3, -1.5, 0] : 0,
        }}
        transition={{
          boxShadow: { duration: 2.2, repeat: Infinity, ease: 'easeInOut' },
          scale: state === 'warning' ? { duration: 0.35, repeat: Infinity } : { duration: 0.08 },
          y: { duration: 0.08 },
          rotate: { duration: 0.6, ease: 'easeInOut' },
        }}
      >
        {photo ? (
          <img src={photo} alt={interviewer?.name || 'Your AI interviewer'} className="h-full w-full object-cover" draggable={false} />
        ) : (
          <User className="h-16 w-16 text-muted-foreground" />
        )}

        <AnimatePresence>
          {state === 'listening' && (
            <motion.div
              key="listening-badge"
              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="absolute bottom-2 rounded-full bg-sky-500/15 border border-sky-400/40 text-sky-500 dark:text-sky-300 text-xs px-3 py-1 flex items-center gap-1.5 backdrop-blur-sm"
            >
              <Ear className="h-3.5 w-3.5" /> Listening…
            </motion.div>
          )}
          {state === 'thinking' && (
            <motion.div
              key="thinking-badge"
              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="absolute bottom-2 rounded-full bg-amber-500/15 border border-amber-400/40 text-amber-600 dark:text-amber-300 text-xs px-3 py-1 flex items-center gap-1.5 backdrop-blur-sm"
            >
              <Brain className="h-3.5 w-3.5" />
              <span className="flex gap-0.5">
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    className="h-1 w-1 rounded-full bg-current inline-block"
                    animate={{ opacity: [0.2, 1, 0.2] }}
                    transition={{ duration: 1, repeat: Infinity, delay: i * 0.2 }}
                  />
                ))}
              </span>
            </motion.div>
          )}
          {state === 'nodding' && (
            <motion.div
              key="nodding-badge"
              initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
              className="absolute bottom-2 rounded-full bg-emerald-500/15 border border-emerald-400/40 text-emerald-600 dark:text-emerald-300 text-xs px-3 py-1 flex items-center gap-1.5 backdrop-blur-sm"
            >
              <motion.span animate={{ rotate: [0, -10, 10, 0] }} transition={{ duration: 0.6 }}>
                <CheckCircle2 className="h-3.5 w-3.5" />
              </motion.span>
              Got it
            </motion.div>
          )}
          {state === 'warning' && (
            <motion.div
              key="warning-badge"
              initial={{ opacity: 0 }} animate={{ opacity: 1, x: [0, -6, 6, -4, 4, 0] }} exit={{ opacity: 0 }}
              transition={{ x: { duration: 0.5 } }}
              className="absolute bottom-2 rounded-full bg-rose-500/15 border border-rose-500/50 text-rose-600 dark:text-rose-300 text-xs px-3 py-1 flex items-center gap-1.5 backdrop-blur-sm"
            >
              <AlertTriangle className="h-3.5 w-3.5" /> Proctoring warning
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {interviewer?.name && (
        <div className="text-sm font-medium text-foreground/80" data-testid="interview-avatar-name">
          {interviewer.name}
        </div>
      )}
    </div>
  );
}
