"""
PART B, step 8: text-to-speech, fully offline.

Engines (TTS_ENGINE in config.py, "auto" tries them in this order):
  piper   - neural voice, sounds natural, runs on CPU (production choice)
  say     - the voice built into macOS (good demo backup, zero setup)
  browser - nothing generated here; the web page speaks with the computer's own voice
Every generated clip is cached by a hash of its text, so repeated answers
(greeting, fallback, popular questions) play instantly.
"""
import hashlib
import re
import logging
import shutil
import subprocess
import threading
import time
import wave

import config

log = logging.getLogger("van_mitra.tts")

_engine = None
_piper_voice = None
_say_voice = None
_lock = threading.Lock()


def _init_piper():
    global _piper_voice
    model = config.MODELS_DIR / "piper" / f"{config.PIPER_VOICE}.onnx"
    if not model.exists():
        return False
    try:
        from piper import PiperVoice
        _piper_voice = PiperVoice.load(str(model))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Piper failed to load: %s", e)
        return False


def installed_say_voices():
    """Names of the macOS voices installed, e.g. ['Samantha', 'Veena', 'Rishi', 'Eddy (English (UK))']."""
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    names = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2,3}_[A-Z]{2,3})\s+#", line)
        if m:
            names.append(m.group(1).strip())
    return names


def _init_say():
    global _say_voice
    if not shutil.which("say"):
        return False
    try:
        names = installed_say_voices()
        wanted = [v.strip() for v in config.MAC_SAY_VOICE.split(",") if v.strip()]
        _say_voice = None
        for w in wanted:
            for variant in (f"{w} (Premium)", f"{w} (Enhanced)", w):
                if variant in names:
                    _say_voice = variant; break
            if _say_voice:
                break
    except Exception:  # noqa: BLE001
        _say_voice = None
    return True


def piper_to_wav(voice, text, wf, speed=1.0):
    """speed = Piper 'length_scale': 1.0 normal, >1 slower."""
    if hasattr(voice, "synthesize_wav"):          # piper-tts >= 1.3
        try:
            from piper import SynthesisConfig
            voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=speed))
        except ImportError:
            voice.synthesize_wav(text, wf)
    else:                                         # piper-tts < 1.3
        voice.synthesize(text, wf, length_scale=speed)


def init():
    global _engine
    want = config.TTS_ENGINE
    order = ["piper", "say"] if want == "auto" else [want]
    for eng in order:
        if eng == "piper" and _init_piper():
            _engine = "piper"; break
        if eng == "say" and _init_say():
            _engine = "say"; break
    else:
        _engine = "browser"
    config.AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("TTS engine: %s%s", _engine, f" (voice {_say_voice or 'default'})" if _engine == "say" else
             (f" ({config.PIPER_VOICE})" if _engine == "piper" else " (browser speaks)"))
    return _engine


def status():
    voice = config.PIPER_VOICE if _engine == "piper" else (_say_voice or "system default") if _engine == "say" else "browser"
    return {"ok": _engine in ("piper", "say"), "engine": _engine, "voice": voice}


def synth(text):
    """Returns (url or None, info). None means: let the browser speak it."""
    if _engine is None:
        init()
    if _engine == "browser":
        return None, {"engine": "browser", "cached": False, "ms": 0}
    key = hashlib.sha1(f"{_engine}|{config.PIPER_VOICE}|{config.PIPER_SPEED}|{_say_voice}|{config.MAC_SAY_RATE}|{text}".encode()).hexdigest()[:16]
    path = config.AUDIO_CACHE_DIR / f"{key}.wav"
    url = f"/static/audio/cache/{key}.wav"
    if path.exists() and path.stat().st_size > 1000:
        return url, {"engine": _engine, "cached": True, "ms": 0}
    t = time.time()
    tmp = path.with_suffix(".tmp.wav")
    try:
        with _lock:
            if _engine == "piper":
                with wave.open(str(tmp), "wb") as wf:
                    piper_to_wav(_piper_voice, text, wf, config.PIPER_SPEED)
            else:
                cmd = ["say", "-r", str(config.MAC_SAY_RATE), "-o", str(tmp), "--data-format=LEI16@22050"]
                if _say_voice:
                    cmd[1:1] = ["-v", _say_voice]
                subprocess.run(cmd + [text], check=True, timeout=30, capture_output=True)
        tmp.replace(path)
        return url, {"engine": _engine, "cached": False, "ms": int((time.time() - t) * 1000)}
    except Exception as e:  # noqa: BLE001
        log.warning("TTS failed (%s) - browser will speak", e)
        return None, {"engine": "browser", "cached": False, "ms": 0, "error": str(e)}
