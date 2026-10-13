"""Speech Service — self-hosted STT (faster-whisper) and TTS (Piper).

Pure audio-in/text-out, text-in/audio-out functions with NO interview-domain
knowledge, so a future move to a dedicated worker/sidecar only touches this
one file. Deliberately self-hosted rather than a paid per-minute API — see
the Mock Interview plan's cost constraint.

Scope, stated plainly: this is turn-based, not streaming. The client uploads
one complete utterance per turn (client-side silence detection decides when
the candidate is done talking); the server transcribes it in a single call.
On CPU-only hardware a 30-60s utterance can realistically take 15-45+ seconds
to transcribe — this is NOT a live-phone-call feel, and callers should surface
a "transcribing..." state rather than assume sub-second latency.
"""
import os
import asyncio
import threading
import io
import logging
import shutil
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small.en")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")

# Speaker verification — detects a DIFFERENT voice answering mid-interview
# (e.g. someone else sitting in for the candidate). MIT-licensed ONNX export
# of pyannote/embedding (trained on VoxCeleb, real human speech) — 512-dim
# embedding from a raw 16kHz mono waveform, no feature engineering needed.
# Chosen over a hand-rolled pitch/spectral fingerprint after that approach
# was empirically tested and rejected: simple acoustic stats couldn't
# reliably separate two different real speakers from one speaker's own
# natural variation (same-speaker deltas were sometimes LARGER than
# different-speaker deltas). This model cleanly separates the two
# (same-speaker cosine similarity ~0.57-0.68 vs different-speaker ~-0.07-0.35
# in direct testing) — see SPEAKER_MATCH_THRESHOLD below.
SPEAKER_EMBEDDING_MODEL_PATH = os.environ.get(
    "SPEAKER_EMBEDDING_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "models", "speaker_embedding", "model.onnx"),
)
SPEAKER_MATCH_THRESHOLD = float(os.environ.get("SPEAKER_MATCH_THRESHOLD", "0.45"))
SPEAKER_MIN_AUDIO_SECONDS = 1.5  # shorter clips produce unreliable embeddings — skip the check, not a false flag
_speaker_session = None

PIPER_BIN = os.environ.get("PIPER_BIN", "piper")
# Piper's own phoneme-duration multiplier — 1.0 is the voice model's natural
# pace. Mock Interview candidates are listening to a new voice cold (no
# visual lip-sync/captions to lean on) and need to actually catch every
# question, so this defaults slower than Piper's out-of-the-box rate rather
# than optimizing for how natural/brisk it sounds.
PIPER_LENGTH_SCALE = float(os.environ.get("PIPER_LENGTH_SCALE", "1.15"))
PIPER_VOICE_MODEL = os.environ.get("PIPER_VOICE_MODEL", "")  # default/fallback path to a .onnx voice model — must be vendored into the deploy image
# Directory holding EVERY interviewer's .onnx voice model (see
# interview_service.INTERVIEWERS) — defaults to PIPER_VOICE_MODEL's own
# directory so a single-voice deploy needs no extra env var.
PIPER_VOICE_DIR = os.environ.get("PIPER_VOICE_DIR") or (os.path.dirname(PIPER_VOICE_MODEL) if PIPER_VOICE_MODEL else "")

_whisper_model = None  # lazy singleton — same idiom as storage_service._client()


class SpeechServiceUnavailableError(Exception):
    """Raised when the self-hosted STT/TTS stack isn't installed/configured
    in this environment — callers should surface a clear "voice unavailable,
    try typing" fallback rather than a raw 500."""


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise SpeechServiceUnavailableError(
                "faster-whisper is not installed — `pip install faster-whisper` "
                "(see requirements.txt) and restart."
            ) from e
        logger.info(f"Loading faster-whisper model={WHISPER_MODEL_SIZE} compute_type={WHISPER_COMPUTE_TYPE}")
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    return _whisper_model


async def warm_up() -> None:
    """Loads (and, the first time ever, downloads) the Whisper model at
    server STARTUP instead of lazily on a candidate's first turn. Model load
    is a one-time ~20-30s cost (weight download/decompression) that has
    nothing to do with per-request transcription speed (~0.5-1.5s once
    warm) — without this, whoever happens to submit the FIRST voice answer
    after any server (re)start eats that whole cold-start as if it were
    normal transcription latency. Best-effort: failures are logged, not
    raised, so a misconfigured/missing faster-whisper install never blocks
    server startup — voice just stays unavailable until fixed, same as
    piper_available()'s degrade-to-text-only story for TTS."""
    try:
        await asyncio.to_thread(_get_whisper_model)
        logger.info("speech_service: faster-whisper model warmed up")
        try:
            from services.interview_service import INTERVIEWERS
            asyncio.create_task(preload_voices([i["voice_file"] for i in INTERVIEWERS]))
        except Exception:
            logger.exception("speech_service: voice preload not started")
    except Exception:
        logger.exception("speech_service: warm_up failed — voice answers will be unavailable until this is fixed")


def _transcribe_sync(audio_path: str) -> str:
    model = _get_whisper_model()
    segments, _info = model.transcribe(audio_path, beam_size=1, vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


async def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """One complete candidate utterance -> transcript text. Blocking faster-whisper
    call is pushed off the event loop via asyncio.to_thread — the same pattern
    storage_service.upload_bytes() uses for boto3's blocking put_object()."""
    if not audio_bytes:
        return ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        return await asyncio.to_thread(_transcribe_sync, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def piper_available(voice_model_path: Optional[str] = None) -> bool:
    model_path = voice_model_path or PIPER_VOICE_MODEL
    return bool(shutil.which(PIPER_BIN)) and bool(model_path) and os.path.exists(model_path)


def voice_model_path(filename: str) -> str:
    """Resolves one of interview_service.INTERVIEWERS' bare .onnx filenames
    to a full path under PIPER_VOICE_DIR, so each interviewer persona can
    ship its own distinct voice without a separate env var per voice."""
    return os.path.join(PIPER_VOICE_DIR, filename) if PIPER_VOICE_DIR else filename


# ---- In-process Piper (voices stay loaded) ---------------------------------
# Spawning the `piper` CLI per sentence reloads a 60-120MB ONNX voice every time (~2.5s of fixed
# latency). Holding PiperVoice objects in memory removes that; the CLI stays as the fallback.
_PIPER_VOICES: Dict[str, Any] = {}
_PIPER_VOICE_LOCKS: Dict[str, "threading.Lock"] = {}
_PIPER_REGISTRY_LOCK = threading.Lock()


def _get_piper_voice(model_path: str):
    with _PIPER_REGISTRY_LOCK:
        voice = _PIPER_VOICES.get(model_path)
        if voice is None:
            from piper import PiperVoice
            voice = PiperVoice.load(model_path)
            _PIPER_VOICES[model_path] = voice
            _PIPER_VOICE_LOCKS[model_path] = threading.Lock()
        return voice, _PIPER_VOICE_LOCKS[model_path]


def _synthesize_inproc_sync(model_path: str, text: str) -> bytes:
    import io
    import wave
    from piper import SynthesisConfig
    voice, lock = _get_piper_voice(model_path)
    buf = io.BytesIO()
    with lock:  # one synthesis at a time per voice (espeak phonemizer is not re-entrant)
        with wave.open(buf, "wb") as wav:
            voice.synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=PIPER_LENGTH_SCALE))
    return buf.getvalue()


async def preload_voices(filenames: List[str]) -> None:
    """Load the interviewer voices into memory in the background so the first turn is fast too."""
    for fn in filenames:
        path = voice_model_path(fn)
        if piper_available(path):
            try:
                await asyncio.to_thread(_get_piper_voice, path)
            except Exception:
                logger.exception(f"speech_service: could not preload voice {fn}")


async def synthesize(text: str, voice_model_path: Optional[str] = None) -> Optional[bytes]:
    """Interviewer's reply text -> WAV bytes via a Piper subprocess. Returns
    None (not raises) if Piper isn't configured in this environment, so the
    turn endpoint can degrade to text-only rather than fail the whole turn —
    voice is an enhancement of the response, not its only valid form.

    `voice_model_path` lets a caller pick a SPECIFIC interviewer's voice
    (see interview_service.INTERVIEWERS); omitted, it falls back to the
    single global PIPER_VOICE_MODEL.

    No long-lived TTS sidecar: Piper's own per-call startup is cheap enough
    that a subprocess per synthesis call is simpler ops than standing up and
    monitoring a second service, and keeps this module a self-contained,
    well-isolated file rather than new infrastructure.
    """
    text = (text or "").strip()
    if not text:
        return None
    model_path = voice_model_path or PIPER_VOICE_MODEL
    if not piper_available(model_path):
        logger.warning(f"speech_service.synthesize: Piper not configured/model missing ({model_path!r}) — skipping TTS")
        return None

    try:
        return await asyncio.to_thread(_synthesize_inproc_sync, model_path, text[:2000])
    except Exception:
        logger.exception("speech_service: in-process Piper failed, falling back to the piper CLI")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_path = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            PIPER_BIN, "--model", model_path, "--output_file", out_path,
            "--length-scale", str(PIPER_LENGTH_SCALE),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(input=text[:2000].encode("utf-8"))
        if proc.returncode != 0:
            logger.warning(f"Piper TTS failed (code {proc.returncode}): {stderr.decode(errors='ignore')[:300]}")
            return None
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


_speaker_sample_rate = 16000


def _get_speaker_session():
    global _speaker_session
    if _speaker_session is None:
        if not os.path.exists(SPEAKER_EMBEDDING_MODEL_PATH):
            raise SpeechServiceUnavailableError(
                f"Speaker-verification model not found at {SPEAKER_EMBEDDING_MODEL_PATH} — "
                "voice-mismatch checks will be skipped until it's vendored."
            )
        import onnxruntime as ort
        logger.info(f"Loading speaker-embedding ONNX model from {SPEAKER_EMBEDDING_MODEL_PATH}")
        _speaker_session = ort.InferenceSession(SPEAKER_EMBEDDING_MODEL_PATH)
    return _speaker_session


def _decode_waveform_sync(audio_bytes: bytes, target_sr: int = _speaker_sample_rate):
    """Raw audio bytes (whatever container the browser's MediaRecorder used,
    typically webm/opus) -> a mono float32 waveform at `target_sr`, via PyAV
    (already a dependency of faster-whisper — no new library needed)."""
    import av
    import numpy as np

    container = av.open(io.BytesIO(audio_bytes))
    stream = container.streams.audio[0]
    resampler = av.AudioResampler(format="s16", layout="mono", rate=target_sr)
    chunks = []
    for frame in container.decode(stream):
        for rframe in resampler.resample(frame):
            arr = rframe.to_ndarray().astype(np.float32).flatten() / 32768.0
            chunks.append(arr)
    container.close()
    return np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)


def _get_voice_embedding_sync(audio_bytes: bytes) -> Optional[List[float]]:
    import numpy as np

    waveform = _decode_waveform_sync(audio_bytes)
    if len(waveform) / _speaker_sample_rate < SPEAKER_MIN_AUDIO_SECONDS:
        return None  # too short for a reliable embedding — not a mismatch, just "can't tell"
    session = _get_speaker_session()
    input_name = session.get_inputs()[0].name
    raw = session.run(None, {input_name: waveform[np.newaxis, :].astype(np.float32)})[0][0]
    norm = np.linalg.norm(raw)
    if norm < 1e-8:
        return None
    return (raw / norm).tolist()


async def get_voice_embedding(audio_bytes: bytes) -> Optional[List[float]]:
    """A 512-dim, L2-normalized voice embedding for one candidate utterance,
    or None if the clip is too short/silent to embed reliably (NOT the same
    as "doesn't match" — callers must treat None as "skip the check this
    turn", never as a mismatch). Returns None (not raises) on any failure —
    same degrade-gracefully contract as the rest of this module; a candidate
    should never be blocked from answering because this optional check broke."""
    if not audio_bytes:
        return None
    try:
        return await asyncio.to_thread(_get_voice_embedding_sync, audio_bytes)
    except Exception:
        logger.exception("speech_service.get_voice_embedding: failed, skipping voice-match check for this turn")
        return None


def cosine_similarity(a: List[float], b: List[float]) -> float:
    import numpy as np
    return float(np.dot(np.array(a), np.array(b)))
