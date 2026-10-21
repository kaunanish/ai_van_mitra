#!/usr/bin/env python3
"""
Downloads every AI model once (needs internet), into ./models.
After this, Van Mitra runs with the network cable unplugged.

  models/whisper/      faster-whisper small.en  (~480 MB)  speech-to-text
  models/embeddings/   bge-small-en-v1.5        (~130 MB)  meaning search
  models/piper/        en_US-lessac-medium      (~60 MB)   voice
The language model (qwen2.5:3b, ~1.9 GB) is pulled by Ollama separately (setup.sh does it).
"""
import shutil
import ssl
import subprocess
import sys
import urllib.request

import config

ok = True


def step(name, fn):
    global ok
    print(f"\n==> {name}")
    try:
        fn()
        print("    done")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"    FAILED: {e}")


def whisper():
    from faster_whisper import WhisperModel
    WhisperModel(config.STT_MODEL, device="cpu", compute_type=config.STT_COMPUTE_TYPE,
                 download_root=str(config.MODELS_DIR / "whisper"))


def embeddings():
    from core.embedder import get_embedder
    e = get_embedder(allow_download=True)
    if e is None:
        raise RuntimeError("embedding model could not be loaded")
    e.embed_query("test")


def download_piper_voice(name):
    """Fetch one Piper voice (e.g. en_US-lessac-medium) into models/piper/. Returns the .onnx path."""
    out = config.MODELS_DIR / "piper"
    out.mkdir(parents=True, exist_ok=True)
    lang, voice, quality = name.split("-")
    sub = f"{lang.split('_')[0]}/{lang}/{voice}/{quality}/{name}"
    for ext in (".onnx", ".onnx.json"):
        dest = out / (name + ext)
        if dest.exists() and dest.stat().st_size > 1000:
            continue
        print(f"    {name + ext}")
        try:  # huggingface_hub (installed with faster-whisper) handles certificates and retries
            from huggingface_hub import hf_hub_download
            p = hf_hub_download("rhasspy/piper-voices", sub + ext, cache_dir=str(out / ".hf-cache"))
            shutil.copyfile(p, dest)
        except ImportError:
            ctx = None
            try:
                import certifi  # python.org builds of Python on macOS lack root certificates
                ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                pass
            url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{sub}{ext}?download=true"
            tmp = dest.with_suffix(dest.suffix + ".part")
            with urllib.request.urlopen(url, timeout=60, context=ctx) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            tmp.replace(dest)
    return out / f"{name}.onnx"


def piper():
    download_piper_voice(config.PIPER_VOICE)


if __name__ == "__main__":
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    step(f"Speech-to-text model (Whisper {config.STT_MODEL})", whisper)
    step(f"Embedding model ({config.EMBED_MODEL})", embeddings)
    step(f"Voice ({config.PIPER_VOICE})", piper)
    if shutil.which("ollama"):
        print(f"\n==> Language model ({config.LLM_MODEL}) via Ollama")
        r = subprocess.run(["ollama", "pull", config.LLM_MODEL])
        ok = ok and r.returncode == 0
    else:
        print("\n==> Ollama not installed - skipping language model (see README).")
    print("\nAll models ready." if ok else "\nSome downloads failed - Van Mitra will still run using its fallbacks. Re-run to retry.")
    sys.exit(0)
