#!/bin/bash
# Double-click to hear every available female voice for Van Mitra.
cd "$(dirname "$0")"
source .venv/bin/activate
python voice_test.py
read -n 1 -s -r -p "Press any key to close..."
