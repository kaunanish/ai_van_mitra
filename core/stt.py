"""
PART B, step 1: speech-to-text with faster-whisper (an optimised, offline version of OpenAI Whisper).

The browser sends a 16 kHz mono WAV file. We hand the raw samples to Whisper and read back
the text plus two quality signals:
  no_speech_prob - how sure Whisper is that there was NO speech at all
  avg_logprob    - how confident it is in the words it wrote (very low = garbled)
If either looks bad we say "Sorry, I didn't catch that" instead of answering the wrong question.
"""
import io
import logging
import threading
import time
import wave

import numpy as np

import config

log = logging.getLogger("van_mitra.stt")

_model = None
_err = ""
_lock = threading.Lock()


def load():
    global _model, _err
    if _model is not None:
        return _model
    try:
        from faster_whisper import WhisperModel
        t = time.time()
        _model = WhisperModel(config.STT_MODEL, device="cpu", compute_type=config.STT_COMPUTE_TYPE,
                              download_root=str(config.MODELS_DIR / "whisper"), local_files_only=True)
        log.info("STT: faster-whisper %s loaded in %.1fs", config.STT_MODEL, time.time() - t)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        _err = ("model not downloaded - run ./setup.sh" if ("snapshot" in msg or "local_files_only" in msg or "not found" in msg.lower())
                else "faster-whisper not installed - run ./setup.sh" if isinstance(e, ImportError) else msg.splitlines()[0][:120])
        log.warning("STT unavailable: %s  (voice questions disabled; typed questions still work)", _err)
        _model = None
    return _model


def status():
    return {"ok": _model is not None, "model": config.STT_MODEL, "detail": "ready" if _model else (_err or "not loaded")}


def read_audio(data: bytes):
    """WAV bytes -> float32 samples at 16 kHz. Other formats are decoded with PyAV (bundled with faster-whisper)."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw != 2:
            raise ValueError("expected 16-bit PCM")
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            x = x.reshape(-1, ch).mean(axis=1)
        if sr != 16000:  # simple linear resample
            n = int(len(x) * 16000 / sr)
            x = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x).astype(np.float32)
        return x
    except (wave.Error, ValueError, EOFError):
        from faster_whisper import decode_audio
        return decode_audio(io.BytesIO(data), sampling_rate=16000)


def transcribe(data: bytes):
    """Returns dict: ok, text, reason, duration_s, no_speech_prob, avg_logprob."""
    audio = read_audio(data)
    dur = len(audio) / 16000.0
    info = {"duration_s": round(dur, 2), "no_speech_prob": None, "avg_logprob": None, "text": ""}
    if dur < config.STT_MIN_AUDIO_S:
        return {**info, "ok": False, "reason": "too_short"}
    audio = audio[: int(config.STT_MAX_AUDIO_S * 16000)]
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    if peak < 0.01:
        return {**info, "ok": False, "reason": "silence"}
    if peak < 0.5:  # gentle normalisation for quiet voices
        audio = audio * (0.5 / peak)
    if load() is None:
        return {**info, "ok": False, "reason": "stt_unavailable"}

    with _lock:
        segments, _ = _model.transcribe(
            audio, language="en", beam_size=1, temperature=0.0, condition_on_previous_text=False,
            initial_prompt=config.STT_INITIAL_PROMPT, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500})
        segments = list(segments)
    if not segments:
        return {**info, "ok": False, "reason": "no_speech"}
    text = " ".join(s.text.strip() for s in segments).strip()
    nsp = float(np.mean([s.no_speech_prob for s in segments]))
    alp = float(np.mean([s.avg_logprob for s in segments]))
    info.update(text=text, no_speech_prob=round(nsp, 3), avg_logprob=round(alp, 3))
    words = [w for w in text.replace(".", " ").split() if w.isalpha() or w.strip("?,!'").isalpha()]
    if nsp > config.STT_NO_SPEECH_MAX or alp < config.STT_MIN_AVG_LOGPROB or len(words) < 1:
        return {**info, "ok": False, "reason": "unclear"}
    return {**info, "ok": True, "reason": ""}
