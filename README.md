# AI Van Mitra: software demo

A talking tree spirit for the Angul Forest Division interpretation centre. A visitor holds a button, asks a question out loud, and Van Mitra answers by voice, using **only** the documents the forest department has approved. It runs fully offline.

This folder holds the complete software. The demo on the Mac and the final standee run the **same code**. Only the inputs differ: the keyboard stands in for the arcade button and the mmWave sensor.

---

## 1. First-time setup (once, with internet)

1. Install **Google Chrome** if it isn't on the Mac already.
2. Install **Ollama** from https://ollama.com/download. Drag it to Applications and open it once. (If you have Homebrew, `setup.sh` installs it for you.)
3. Open **Terminal** and run:

```bash
cd ~/Downloads/Anish/Project/"Angul exhibition"/"AI van mitra demo"
chmod +x setup.sh run.sh
./setup.sh
```

Setup creates a private Python environment (`.venv`), installs the libraries, and downloads the AI models into `models/`. That's about 2.5 GB in total, including the 1.9 GB language model. Then it builds the knowledge index. It takes 10–20 minutes the first time.

## 2. Running it

```bash
./run.sh          # demo: portrait screen + "How I answered" panel (use this on 22 Oct)
./run.sh kiosk    # full-screen kiosk, exactly as on the 32" display
```

The first time, macOS will ask whether **Google Chrome may use the microphone**. Click **Allow**.

| Key | What it does | In the real standee |
|---|---|---|
| **Space** (hold) | Press & Ask button: hold it, speak, then let go | 60 mm arcade button |
| **P** | A visitor arrives / leaves | mmWave presence sensor |
| **T** | Type a question (backup if the room is noisy) | not used |
| **H** | Show or hide the "How I answered" panel | hidden |
| **F** | Full screen | kiosk mode |

Admin statistics: http://localhost:5055/admin (PIN **2026**; change `ADMIN_PIN` in `config.py`).

---

## 3. How it works

### Part A: preparing the knowledge (`build_index.py`)

The forest department's material arrives as ordinary documents (PDF, Word, text), not as ready-made question-and-answer pairs. So Van Mitra works like an **open-book exam**:

1. **Read** every file in `knowledge/docs/`: PDF via PyMuPDF, Word via python-docx, plus OCR for scanned pages if Tesseract is installed.
2. **Clean** the text: repeating headers/footers and page numbers are removed, and hyphenated line-breaks are joined.
3. **Chunk** it into passages of ~150–250 words at paragraph/heading boundaries, with ~40 words of overlap so no fact is cut in half.
4. **Embed** each passage with `bge-small-en-v1.5`. This turns its *meaning* into 384 numbers, so "big cat" and "tiger" end up close together.
5. **Keyword index** (BM25) for exact names like *Satkosia* or *Tikarpada*.
6. Everything is saved to `knowledge/index/` as plain files. No database server is needed.
7. `knowledge/pinned.json` holds hand-written answers for questions that must be word-perfect (helplines, timings).

`run.sh` rebuilds the index automatically whenever a document changes.

### Part B: answering a question (`app.py` + `core/`)

| Step | File | What happens |
|---|---|---|
| 1. Hear | `core/stt.py` | The browser records 16 kHz audio. **faster-whisper** (offline Whisper) writes it as text. If Whisper isn't confident (no speech, or garbled), Van Mitra says *"Sorry, I didn't catch that"* instead of answering the wrong question. |
| 2. Small talk | `core/rules.py` | "Hello", "who are you", "thank you" and "bye" get instant friendly replies. |
| 3. Pinned | `core/retriever.py` | If the question closely matches a pinned question (similarity ≥ 0.85), the exact approved answer is used. |
| 4. Search | `core/retriever.py` | **Hybrid search**: meaning similarity *and* BM25 keywords, merged by Reciprocal Rank Fusion (each list gives 1/(60+rank)). The top 4 passages are kept. |
| 5. **Gate 1** | `core/retriever.py` | If even the best passage isn't similar enough (cosine < 0.50), the language model is **never called**. Van Mitra says: *"I don't have that information yet. Please ask our forest staff at the desk!"* |
| 6. Answer | `core/llm.py` | A small local model (**Qwen2.5 3B** via Ollama, temperature 0.1) answers in 2–3 simple sentences, **only from those passages**. |
| 7. **Gate 2** | `core/llm.py` | The model must reply `NOT_FOUND` if the passages don't contain the answer, which also leads to the polite fallback. Markdown is stripped and long answers are trimmed. |
| 8. Speak | `core/tts.py` | **Piper** (offline neural voice) creates the audio. Clips are cached, so repeated answers play instantly. |
| 9. Log | `core/logger.py` | Question, route, passages, scores and timings go into SQLite (`data/`). This powers the admin page, especially the list of **unanswered questions**, which tells the DFO what content to add. |

Two gates mean Van Mitra cannot invent facts. Either the answer is in the approved documents, or it politely says it doesn't know.

### The screen (`static/`)

Plain HTML/CSS/JavaScript with no frameworks.

* **State machine** (`app.js`): IDLE (attract loop) → visitor detected → GREETING → READY → button held → LISTENING (max 10 s) → THINKING → SPEAKING → READY. It returns to IDLE after 30 s with nobody present, or 45 s with no activity. Pressing the button while Van Mitra is speaking interrupts it.
* **Character**: an SVG tree spirit animated with CSS (blinking, swaying canopy, waving branch). Its **mouth follows the loudness of its own voice**, measured live with the Web Audio `AnalyserNode`. Subtitles light up word by word.
* **Glow and LED colour** follow the state: green = ready, blue = listening, amber = thinking. The same colours are sent to the LED ring around the physical button.
* The microphone stays open, and ~0.2 s from *before* the button press is kept, so the first word is never cut off.

### Hardware link (`core/hardware.py`, `firmware/`)

The Arduino sends `BTN_DOWN`, `BTN_UP`, `PRESENCE_ON` and `PRESENCE_OFF` over USB serial. Flask reads them in a background thread and pushes them to the browser with **Server-Sent Events** (`/events`). The browser reports each state change back (`POST /api/state`), and Flask sends `LED:<STATE>` to the Arduino.

In the demo, the keyboard posts the **same event names** to `/api/hw`, which travel the same SSE path. To use real hardware, set the port: `SERIAL_PORT=/dev/tty.usbserial-XXXX ./run.sh kiosk`.

### Fallbacks, so the demo never breaks

| If this is missing… | Van Mitra still works by… |
|---|---|
| Ollama / language model | speaking the best-matching sentences **exactly as written** in the documents |
| Embedding model | keyword-only search, with a keyword-coverage gate |
| Piper voice | the Mac's built-in voice (`say`), else the browser's voice |
| Whisper / microphone | typed questions (**T**) |

The **System** list at the top of the panel shows which parts are running.

---

## 4. Demo plan for 22 October

Before the meeting: run `./setup.sh` at home with internet. At the venue, **turn Wi-Fi off** before starting. That proves it is offline.

1. `./run.sh`. The panel is open on the right. Point out that every system light is green, and that Wi-Fi is off.
2. Press **P** (a visitor walks up). Van Mitra waves and greets.
3. Hold **Space**: *"What does Satkosia mean?"* Release. Show the panel: what it heard, the 4 passages found with their scores, the gate passing, the model's answer, and the time taken.
4. *"What should I do if I see an elephant?"* shows a safety message drawn from the forest department's own guidance.
5. *"Who won the cricket world cup?"* The gate **blocks** it, the model is never asked, and Van Mitra politely sends the visitor to the staff. **This is the key point: it never makes things up.**
6. Press Space while it is talking to show that a child can interrupt it.
7. Open `/admin`. The cricket question now sits in **"Questions Van Mitra could not answer"**, so the DFO knows exactly what content to add.
8. If the room is too noisy for the microphone, press **T** and type the same questions.

---

## 5. Changing the content

* Put DFO documents (PDF, DOCX, TXT, MD) in `knowledge/docs/`, then delete or keep the sample files.
* Edit `knowledge/pinned.json` for answers that must be exact.
* Restart `./run.sh`. The index rebuilds itself.

> The six sample files in `knowledge/docs/` were compiled from public sources for this demo only. Replace them with, or have them checked against, the forest department's own material before installation.

## 6. Tuning (all in `config.py`)

| Setting | Default | Meaning |
|---|---|---|
| `GATE_COSINE` | 0.50 | Raise it if off-topic questions get answers; lower it if real questions get the fallback. The panel shows the value for every question. |
| `LLM_MODEL` | `qwen2.5:3b` | Alternatives: `llama3.2:3b`, `gemma3:4b` (`ollama pull <name>`) |
| `STT_MODEL` | `small.en` | `base.en` is faster but less accurate |
| `PIPER_VOICE` / `TTS_ENGINE` | `en_US-lessac-medium` / `auto` | `TTS_ENGINE=say ./run.sh` uses the Mac's voice (`MAC_SAY_VOICE=Rishi` for Indian English) |

## 7. Files

```
app.py              Flask server: routes, answer pipeline, SSE
config.py           every threshold, model name and path
build_index.py      Part A: documents -> passages -> embeddings + keywords
download_models.py  one-time model download (called by setup.sh)
core/
  stt.py            speech-to-text (faster-whisper) + quality check
  rules.py          small-talk replies
  embedder.py       meaning vectors (bge-small-en-v1.5)
  bm25.py           keyword search formula
  retriever.py      pinned answers, hybrid search, relevance gate
  llm.py            Ollama call, NOT_FOUND check, no-LLM fallback
  tts.py            Piper / macOS voice, cached
  hardware.py       serial thread, event bus, LED commands
  logger.py         SQLite logging + statistics
knowledge/docs/     source documents        knowledge/pinned.json   exact answers
knowledge/index/    generated index         models/                 downloaded AI models
static/             kiosk page (index.html, style.css, app.js, fonts)
admin/              PIN-protected statistics page
firmware/           Arduino sketch: button, mmWave sensor, LED ring
setup.sh / run.sh   install / start
```

## 8. Troubleshooting

* **"Speech to text" is red**: run `./setup.sh` again with internet (the Whisper model didn't download).
* **"Language model" is amber**: open the Ollama app, or run `ollama pull qwen2.5:3b`.
* **Van Mitra doesn't hear anything**: check System Settings → Privacy & Security → Microphone → Google Chrome is on. Then click the page once and press Space.
* **Port already in use**: `PORT=5056 ./run.sh`.
* **First answer is slow**: the model loads into memory at start-up. Wait for "Van Mitra is ready" in the Terminal.
