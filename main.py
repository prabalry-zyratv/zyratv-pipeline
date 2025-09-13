import os, glob, re, hashlib
from typing import Tuple, Dict
from tts import text_to_speech
from video import make_video
import yaml

SCRIPTS_ROOT = "input/scripts"
AUDIO_DIR = "output/audio"
FINAL_DIR = "output/final"

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)

FM_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

def parse_script(path: str) -> Tuple[Dict, str]:
    """Return (meta, body_text). Meta from YAML front-matter if present."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    m = FM_RE.match(raw)
    if m:
        fm_yaml, body = m.group(1), m.group(2)
        meta = yaml.safe_load(fm_yaml) or {}
    else:
        meta, body = {}, raw
    fname = os.path.splitext(os.path.basename(path))[0]
    meta.setdefault("id", fname)
    meta.setdefault("lang", "en")
    parent = os.path.basename(os.path.dirname(path))
    if parent and parent not in (".", "scripts"):
        meta.setdefault("channel_code", parent)
    body = body.replace("\r\n", "\n").strip()
    return meta, body

def already_done(script_id: str) -> bool:
    return os.path.exists(os.path.join(FINAL_DIR, f"{script_id}.mp4"))

def safe_id(s: str) -> str:
    s2 = re.sub(r"[^A-Za-z0-9_\-]+", "-", s).strip("-")
    return s2 or hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]

def discover_scripts():
    patterns = [os.path.join(SCRIPTS_ROOT, "**", "*.md"),
                os.path.join(SCRIPTS_ROOT, "**", "*.txt")]
    files = []
    for p in patterns:
        files.extend(glob.glob(p, recursive=True))
    return sorted(files)

def run_pipeline(limit: int = 0):
    files = discover_scripts()
    if not files:
        print(f"❌ No scripts found under {SCRIPTS_ROOT}/")
        return
    produced = 0
    for idx, path in enumerate(files, start=1):
        meta, body = parse_script(path)
        script_id = safe_id(meta.get("id", os.path.splitext(os.path.basename(path))[0]))
        lang = meta.get("lang", "en")
        if not body:
            print(f"⚠️ Skipping empty script: {path}")
            continue
        if already_done(script_id):
            print(f"⏭️  Skipping {script_id} (final MP4 exists)")
            continue
        print(f"\n🎬 [{idx}/{len(files)}] {script_id} | {meta.get('channel_code','?')} | lang={lang}")
        audio_path = os.path.join(AUDIO_DIR, f"{script_id}.mp3")
        text_to_speech(body, audio_path)
        try:
            final_video = make_video(audio_path, body)
            print(f"✅ Done: {final_video}")
            produced += 1
        except Exception as e:
            print(f"❌ Failed {script_id}: {e}")
        if limit and produced >= limit:
            print(f"\n✅ Limit reached ({limit}). Stopping.")
            break
    print(f"\n🎉 Finished. Produced: {produced} videos.")

if __name__ == "__main__":
    limit_env = os.getenv("VIDEOS_LIMIT", "").strip()
    limit = int(limit_env) if limit_env.isdigit() else 0
    run_pipeline(limit=limit)
