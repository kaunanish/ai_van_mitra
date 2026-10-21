#!/bin/bash
# =============================================================================
#  AI Van Mitra - one-time setup on a Mac (needs internet, ~3 GB download).
#  Usage:   cd "AI van mitra demo"   then   ./setup.sh
# =============================================================================
set -e
cd "$(dirname "$0")"

green(){ printf "\033[32m%s\033[0m\n" "$*"; }
warn(){ printf "\033[33m%s\033[0m\n" "$*"; }

# 1. pick a Python 3.9+ (prefer a newer Homebrew one)
PY=""
for c in python3.12 python3.11 python3.13 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  warn "Python 3.9+ not found. Install it with:  xcode-select --install   (or: brew install python@3.12)"
  exit 1
fi
green "Using $($PY --version) ($PY)"

# 2. virtual environment (keeps Van Mitra's libraries separate from the rest of the Mac)
if [ ! -d .venv ]; then
  $PY -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip wheel >/dev/null

# 3. libraries: core ones must install; AI ones are tried one by one so one failure doesn't stop the rest
green "Installing core libraries..."
pip install "flask>=3.0" "waitress>=3.0" "numpy>=1.24"
for pkg in "faster-whisper>=1.0" "fastembed>=0.3" "piper-tts>=1.3" "pymupdf>=1.23" "python-docx>=1.0" "pyserial>=3.5"; do
  green "Installing $pkg ..."
  pip install "$pkg" || warn "  could not install $pkg - Van Mitra will use its fallback for this part"
done

# 4. Ollama (the local language-model server)
if ! command -v ollama >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    green "Installing Ollama with Homebrew..."
    brew install ollama || true
  fi
fi
if command -v ollama >/dev/null 2>&1; then
  if ! curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    green "Starting Ollama..."
    (ollama serve >/tmp/ollama.log 2>&1 &)
    sleep 3
  fi
else
  warn "Ollama is not installed. Download it from https://ollama.com/download (drag to Applications, open once),"
  warn "then run ./setup.sh again. Without it Van Mitra answers with exact sentences from the documents."
fi

# 5. models
green "Downloading AI models (one time)..."
python download_models.py

# 6. knowledge index
green "Building the knowledge index from knowledge/docs ..."
python build_index.py

chmod +x run.sh
green ""
green "Setup complete.  Start Van Mitra with:   ./run.sh"
