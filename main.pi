# src/main.py

import os
import csv
from tts import text_to_speech
from video import make_video

SCRIPTS_CSV = "input/scripts.csv"
AUDIO_DIR = "output/audio/"
FINAL_DIR = "output/final/"

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)

def read_scripts(csv_file):
    """
    Reads CSV file with scripts.
    Returns a list of tuples: (script_id, script_text)
    """
    scripts = []
    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            script_id = row[0].strip()
            script_text = row[1].strip()
            scripts.append((script_id, script_text))
    return scripts

def run_pipeline():
    scripts = read_scripts(SCRIPTS_CSV)

    for idx, (script_id, script_text) in enumerate(scripts, start=1):
        print(f"\n🎬 Processing Script {idx} ({script_id})...")

        # 1️⃣ Convert to audio
        audio_path = os.path.join(AUDIO_DIR, f"{script_id}.mp3")
        text_to_speech(script_text, audio_path)

        # 2️⃣ Create video with Pexels videos
        try:
            final_video = make_video(audio_path, script_text)
            print(f"✅ Video created: {final_video}")
        except Exception as e:
            print(f"⚠️ Skipped Script {script_id}: {e}")

    print("\n🎉 SUCCESS: All scripts converted into reels!")

if __name__ == "__main__":
    run_pipeline()
