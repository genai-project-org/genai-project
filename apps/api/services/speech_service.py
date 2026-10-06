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
import logging
import shutil
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small.en")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")

PIPER_BIN = os.environ.get("PIPER_BIN", "piper")
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

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_path = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            PIPER_BIN, "--model", model_path, "--output_file", out_path,
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
