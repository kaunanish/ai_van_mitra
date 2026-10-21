"""
AI Van Mitra - central configuration.

Every tunable number lives here so it can be adjusted on site without
touching the logic. Values can also be overridden with environment
variables of the same name (e.g.  GATE_COSINE=0.55 ./run.sh).
"""
import os
from pathlib import Path


def _env(name, default, cast=str):
    val = os.environ.get(name)
    if val is None:
        return default
    if cast is bool:
        return val.strip().lower() in ("1", "true", "yes", "on")
    return cast(val)


BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------- paths
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
DOCS_DIR = KNOWLEDGE_DIR / "docs"
INDEX_DIR = KNOWLEDGE_DIR / "index"
PINNED_FILE = KNOWLEDGE_DIR / "pinned.json"
MODELS_DIR = BASE_DIR / "models"           # all downloaded AI models live here (offline after setup)
STATIC_DIR = BASE_DIR / "static"
AUDIO_CACHE_DIR = STATIC_DIR / "audio" / "cache"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "van_mitra.sqlite3"

# ---------------------------------------------------------------- server
HOST = _env("HOST", "127.0.0.1")
PORT = _env("PORT", 5055, int)              # not 5000: macOS AirPlay uses 5000
ADMIN_PIN = _env("ADMIN_PIN", "2026")
# Optional extras - OFF, because they were not part of the submitted bid.
# Turn on only if the DFO asks for them (e.g. ENABLE_ADMIN=1 ./run.sh).
ENABLE_ADMIN = _env("ENABLE_ADMIN", False, bool)      # /admin statistics page
ENABLE_LOGGING = _env("ENABLE_LOGGING", False, bool)  # save questions/visits to data/van_mitra.sqlite3

# ---------------------------------------------------------------- knowledge preparation (build_index.py)
CHUNK_MIN_WORDS = 150
CHUNK_MAX_WORDS = 250
CHUNK_OVERLAP_WORDS = 40

# ---------------------------------------------------------------- embeddings (meaning search)
EMBED_MODEL = _env("EMBED_MODEL", "BAAI/bge-small-en-v1.5")   # 384-dim
# bge models work best when the *query* gets this prefix (documents do not)
EMBED_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# ---------------------------------------------------------------- retrieval + gates
TOP_K = 4                                   # passages given to the LLM
RRF_K = 60                                  # Reciprocal Rank Fusion constant: score = 1/(RRF_K + rank)
GATE_COSINE = _env("GATE_COSINE", 0.50, float)      # gate 1: best meaning-similarity must reach this
GATE_BM25_FALLBACK = _env("GATE_BM25", 0.35, float) # gate 1 when no embedding model: keyword coverage 0..1
PINNED_THRESHOLD = _env("PINNED_THRESHOLD", 0.85, float)
PINNED_THRESHOLD_KEYWORD = 0.75             # same, when no embedding model (token overlap)

# ---------------------------------------------------------------- LLM (Ollama, local)
OLLAMA_URL = _env("OLLAMA_URL", "http://127.0.0.1:11434")
LLM_MODEL = _env("LLM_MODEL", "qwen2.5:3b")
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 120
LLM_TIMEOUT_S = 30
LLM_KEEP_ALIVE = "24h"                      # keep the model loaded in RAM -> fast answers
MAX_ANSWER_SENTENCES = 3

SYSTEM_PROMPT = """You are Van Mitra, a friendly talking tree spirit who guides visitors at a forest interpretation centre in Angul, Odisha.
Rules you must always follow:
1. Answer ONLY using facts written in the CONTEXT below. Never use outside knowledge, never guess.
2. If the CONTEXT does not contain the answer, reply with exactly: NOT_FOUND
3. Answer in 2 or 3 short, simple sentences that a 10-year-old child can understand.
4. Plain spoken English only: no lists, no bullet points, no headings, no markdown, no emojis.
5. Do not mention the CONTEXT, documents or passages. Speak naturally, as yourself.
6. You are in Odisha. Copy place names exactly as written in the CONTEXT and never name any other state or city that is not in the CONTEXT."""

# ---------------------------------------------------------------- speech-to-text (faster-whisper)
STT_MODEL = _env("STT_MODEL", "small.en")   # "base.en" is faster, "small.en" more accurate
STT_COMPUTE_TYPE = "int8"
STT_NO_SPEECH_MAX = 0.6                     # above this -> "didn't catch that"
STT_MIN_AVG_LOGPROB = -1.0                  # below this -> garbled
STT_MIN_AUDIO_S = 0.4
STT_MAX_AUDIO_S = 10.0
# helps Whisper spell local names correctly
STT_INITIAL_PROMPT = ("Van Mitra, Angul, Anugul, Satkosia, Mahanadi, Tikarpada, Baisipalli, gharial, "
                      "mugger, sambar, chital, sal, mahua, kendu, Odisha, DFO.")

# ---------------------------------------------------------------- text-to-speech
# "auto" = Piper if its voice model is present, else macOS 'say', else browser voice
TTS_ENGINE = _env("TTS_ENGINE", "say")   # "say" = macOS Indian-English voice (Piper has no Indian-English voice)
PIPER_VOICE = _env("PIPER_VOICE", "en_US-lessac-medium")    # female, clear American English
PIPER_SPEED = _env("PIPER_SPEED", 1.15, float)               # 1.0 = normal; higher = slower (1.15 ~ 15% slower)
# macOS voices: the first one installed on this Mac is used.
# Isha / Veena = Indian-English female, Samantha = US female, Rishi = Indian-English male
# "(Premium)" / "(Enhanced)" downloads of a voice are picked automatically when installed.
MAC_SAY_VOICE = _env("MAC_SAY_VOICE", "Isha,Veena,Samantha")
MAC_SAY_RATE = _env("MAC_SAY_RATE", 155, int)                # words per minute (macOS default is ~175-180)

# ---------------------------------------------------------------- hardware bridge (production)
SERIAL_PORT = _env("SERIAL_PORT", "")       # e.g. /dev/tty.usbserial-1410 ; empty = demo mode (keyboard)
SERIAL_BAUD = 115200

# ---------------------------------------------------------------- fixed lines
GREETING_TEXT = ("Namaskar! I am Van Mitra, the friend of the forest. "
                 "Press and hold the green button, ask me anything about the forests and wildlife of Angul, "
                 "then let go.")
FALLBACK_TEXT = "I don't have that information yet. Please ask our forest staff at the desk!"
NOT_HEARD_TEXT = "Sorry, I didn't catch that. Please hold the button and ask me again, a little closer to the microphone."
TOO_SHORT_TEXT = "Please keep holding the button while you speak, and let go when you finish."
ERROR_TEXT = "Oh! My leaves got tangled for a moment. Please ask me again."
