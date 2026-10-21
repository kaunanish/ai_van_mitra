#!/usr/bin/env python3
"""
Plays a short sample in every female voice available, so you can pick one for Van Mitra.
Run it by double-clicking "Test Voices.command" (needs internet the first time, for the Piper voices).

Then set your choice in config.py:
    Piper voice : TTS_ENGINE = "piper"   and  PIPER_VOICE = "<name>"
    macOS voice : TTS_ENGINE = "say"     and  MAC_SAY_VOICE = "<name>"
"""
import subprocess
import tempfile
import wave
from pathlib import Path

import config
from core.tts import installed_say_voices, piper_to_wav

SAMPLE = ("Namaskar! I am Van Mitra, the friend of the forest. "
          "The gharial is a crocodile with a very long, thin snout, and it lives in the Mahanadi river.")

# female English voices that ship with (or can be added to) macOS
MAC_FEMALE = {
    "Veena": "Indian English", "Isha": "Indian English", "Lekha": "Indian English (Hindi voice)",
    "Samantha": "American", "Ava": "American", "Allison": "American", "Susan": "American", "Zoe": "American",
    "Karen": "Australian", "Moira": "Irish", "Tessa": "South African", "Fiona": "Scottish",
    "Serena": "British", "Kate": "British", "Martha": "British",
}
# free, offline neural voices (Piper) - all female
PIPER_FEMALE = {
    "en_US-lessac-medium": "American, clear (current default)",
    "en_US-amy-medium": "American, warm",
    "en_US-hfc_female-medium": "American, bright",
    "en_GB-jenny_dioco-medium": "British",
    "en_GB-alba-medium": "Scottish",
    "en_GB-southern_english_female-low": "British, softer",
}

n = 0


def header(text):
    global n
    n += 1
    print(f"\n  {n:>2}. {text}")


def play(path):
    subprocess.run(["afplay", str(path)])


print("\n=== macOS voices (built in) - rate", config.MAC_SAY_RATE, "words/min ===")
try:
    installed = installed_say_voices()
except Exception:  # noqa: BLE001
    installed = []
found = False
for base, accent in MAC_FEMALE.items():
    matches = [v for v in installed if v == base or v.startswith(base + " (")]
    for v in matches:
        found = True
        header(f'{v}  -  {accent}            MAC_SAY_VOICE = "{v}"')
        subprocess.run(["say", "-v", v, "-r", str(config.MAC_SAY_RATE), SAMPLE])
if not found:
    print("  (no female English macOS voices found)")
missing = [v for v in ("Veena", "Isha") if not any(x == v or x.startswith(v + " (") for x in installed)]
if missing:
    print(f"\n  Tip: the Indian-English voices {', '.join(missing)} can be added in System Settings > Accessibility >")
    print("  Spoken Content > System voice > Manage Voices... > English (India). Then run this test again.")

print(f"\n=== Piper voices (natural, offline) - speed {config.PIPER_SPEED} (1.0 = normal, higher = slower) ===")
try:
    from piper import PiperVoice
    from download_models import download_piper_voice
    for name, desc in PIPER_FEMALE.items():
        try:
            model = download_piper_voice(name)
            voice = PiperVoice.load(str(model))
            out = Path(tempfile.gettempdir()) / f"vm_{name}.wav"
            with wave.open(str(out), "wb") as wf:
                piper_to_wav(voice, SAMPLE, wf, config.PIPER_SPEED)
            header(f'{name}  -  {desc}            PIPER_VOICE = "{name}"')
            play(out)
        except Exception as e:  # noqa: BLE001
            print(f"  could not load {name}: {e}")
except ImportError:
    print("  Piper is not installed (run ./setup.sh).")

print("\nDone. Tell Claude the number you liked, or set it in config.py as shown next to it.\n")
