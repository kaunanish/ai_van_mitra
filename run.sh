#!/bin/bash
# =============================================================================
#  AI Van Mitra - start everything.
#    ./run.sh           demo window (talking tree + subtitles)
#    ./run.sh kiosk     full-screen kiosk, exactly as on the 32" display
#    ./run.sh server    server only (open http://localhost:5055 yourself)
#  Stop with Ctrl+C in this window.
# =============================================================================
cd "$(dirname "$0")"
MODE="${1:-demo}"
PORT="${PORT:-5055}"
URL="http://localhost:$PORT"

if [ ! -d .venv ]; then echo "Run ./setup.sh first."; exit 1; fi
source .venv/bin/activate

# 1. Ollama running? (the language model server)
if command -v ollama >/dev/null 2>&1 && ! curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Starting Ollama..."
  if [ -d /Applications/Ollama.app ]; then open -g -a Ollama; else (ollama serve >/tmp/ollama.log 2>&1 &); fi
  for i in 1 2 3 4 5 6 7 8 9 10; do curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
fi

# 2. rebuild the knowledge index if any document is newer than it
if [ ! -f knowledge/index/chunks.json ] || [ -n "$(find knowledge/docs knowledge/pinned.json -newer knowledge/index/chunks.json -type f 2>/dev/null | head -1)" ]; then
  echo "Documents changed - rebuilding knowledge index..."
  python build_index.py || exit 1
fi

# 3. backend
python app.py &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; exit' INT TERM EXIT
for i in $(seq 1 30); do curl -s "$URL/api/status" >/dev/null 2>&1 && break; sleep 0.5; done

[ "$MODE" = "server" ] && { echo "Server running at $URL"; wait $SERVER; exit; }

# 4. Chrome in app/kiosk mode with its own profile:
#    - microphone allowed automatically, sound may play without a click
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FLAGS=(--user-data-dir="$PWD/.chrome-profile" --no-first-run --no-default-browser-check
       --autoplay-policy=no-user-gesture-required
       --disable-features=Translate --overscroll-history-navigation=0)
# allow the microphone for Van Mitra's own page in this private Chrome profile (no warning bar, no pop-up)
python3 - "$PWD/.chrome-profile/Default/Preferences" "$URL" <<'PY' 2>/dev/null
import json, sys, os
path, url = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(path), exist_ok=True)
try:
    prefs = json.load(open(path))
except Exception:
    prefs = {}
ex = prefs.setdefault("profile", {}).setdefault("content_settings", {}).setdefault("exceptions", {})
ex.setdefault("media_stream_mic", {})[url + ",*"] = {"setting": 1}
json.dump(prefs, open(path, "w"))
PY
if [ -x "$CHROME" ]; then
  if [ "$MODE" = "kiosk" ]; then
    "$CHROME" "${FLAGS[@]}" --kiosk "$URL/?kiosk=1" >/dev/null 2>&1 &
  else
    "$CHROME" "${FLAGS[@]}" --app="$URL/" --start-maximized >/dev/null 2>&1 &
  fi
else
  echo "Google Chrome not found - opening the default browser (allow the microphone when asked)."
  open "$URL/"
fi

echo ""
echo "Van Mitra is running at $URL"
echo "Keys: hold SPACE = Press & Ask button, P = visitor arrives/leaves, F = full screen"
echo "Press Ctrl+C here to stop."
wait $SERVER
