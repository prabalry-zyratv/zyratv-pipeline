# video.py — Serverless-friendly renderer for ZyraTV
# - Works on Ubuntu GitHub Actions (no Windows paths, no ImageMagick)
# - Handles long scripts by using 1–3 background clips (paragraph-weighted)
# - Uses PEXELS_API_KEY from env; falls back to a solid color if API/rate-limit fails
# - Respects meta from main.py (id, channel_code, image_query, etc.)

import os
import re
import requests
from typing import List, Optional, Dict
from moviepy.editor import (
    VideoFileClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip, vfx, ColorClip
)

# Folders (outputs are later uploaded to Google Drive by the GitHub Action)
MEDIA_DIR = "input/media_temp"
OUT_DIR   = "output/final"
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(OUT_DIR,   exist_ok=True)

# Render settings
TARGET_W, TARGET_H, FPS = 1080, 1920, 30
BITRATE = "8000k"   # 8–10 Mbps is fine for 1080x1920

# ------------------------ Helpers ------------------------

def _verticalize(clip: VideoFileClip) -> VideoFileClip:
    """Scale & center-crop to 1080x1920 (9:16)."""
    c = clip.resize(height=TARGET_H)
    if c.w < TARGET_W:
        c = clip.resize(width=TARGET_W)
    x1 = max(0, (c.w - TARGET_W) / 2)
    return c.crop(x1=x1, y1=0, x2=x1 + TARGET_W, y2=TARGET_H)

def _safe_loop(clip: VideoFileClip, duration: float) -> VideoFileClip:
    """Loop/trim a clip safely to exact duration."""
    if duration <= 0.1:
        duration = 0.1
    try:
        return clip.fx(vfx.loop, duration=duration)
    except Exception:
        return clip.set_duration(duration)

def _paragraphs(script_text: str) -> List[str]:
    """Split by blank lines; fallback to whole text."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", (script_text or "").strip()) if p.strip()]
    return paras if paras else [script_text.strip()]

def _derive_query(script_text: str, meta: Optional[Dict]) -> str:
    """Choose a background search query (prefers explicit front-matter)."""
    if meta and meta.get("image_query"):
        return str(meta["image_query"]).strip()

    code = (meta or {}).get("channel_code", "").upper()
    text = (script_text or "").lower()

    # Families you asked for
    if code.startswith("HM-") or any(k in text for k in ("mytholog", "ramayan", "mahabharat", "krishna", "shiva")):
        return "hindu temple sunrise clouds incense"
    if code.startswith("HT-") or any(k in text for k in ("tantra", "ritual", "haunted", "ghost", "horror")):
        return "night forest fog moonlight candle ritual"
    if code.startswith("MJ-") or any(k in text for k in ("resume", "interview", "job", "career", "cv", "hiring")):
        return "office laptop city skyline night bokeh"

    # Generic safe fallback
    return "abstract motion background particles"

def _pexels_pick(query: str, need: int = 3) -> List[str]:
    """
    Return up to `need` direct video URLs from Pexels (highest quality per result).
    We do not download; FFmpeg can read HTTP URLs directly.
    """
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key or not query:
        return []

    try:
        url = "https://api.pexels.com/videos/search"
        resp = requests.get(
            url,
            params={"query": query, "per_page": max(need * 3, 6)},
            headers={"Authorization": api_key},
            timeout=30,
        )
        if not resp.ok:
            return []
        data = resp.json()
        vids = []
        for v in data.get("videos", []):
            files = sorted(
                v.get("video_files", []),
                key=lambda f: (f.get("height", 0), f.get("width", 0)),
                reverse=True,
            )
            for f in files:
                link = f.get("link")
                if link and link.startswith("http"):
                    vids.append(link)
                    break
            if len(vids) >= need:
                break
        return vids
    except Exception:
        return []

# ------------------------ Main ------------------------

def make_video(audio_path: str, script_text: str, meta: Optional[Dict] = None) -> str:
    """
    Build a vertical 1080x1920 MP4 for the given audio+script.
    Strategy:
      - 1–3 segments max, durations proportional to paragraph lengths
      - Minimal Pexels lookups (serverless-friendly)
      - Solid color fallback if nothing fetched / rate-limited
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    # Load narration
    narration = AudioFileClip(audio_path)
    total_dur = max(0.1, narration.duration)

    # Decide visual query & fetch a few candidates
    query = _derive_query(script_text, meta)
    need = int(os.getenv("SEGMENTS", "3"))  # default 3 background segments
    urls = _pexels_pick(query, need=need)

    # Turn URLs into verticalized clips (or fallback)
    vclips: List[VideoFileClip] = []
    for url in urls:
        try:
            c = VideoFileClip(url)
            vclips.append(_verticalize(c))
        except Exception:
            # network/file issues — skip and try next
            pass

    if not vclips:
        # Fallback background if API fails or rate-limited
        bg = ColorClip(size=(TARGET_W, TARGET_H), color=(10, 10, 14)).set_fps(FPS)
        vclips = [bg]

    # Allocate durations by paragraph weights (paragraph count may exceed clips)
    paras = _paragraphs(script_text)
    count = min(len(vclips), max(1, len(paras)))
    weights = [len(p) for p in paras[:count]]
    wsum = sum(weights) or 1.0
    seg_durs = [total_dur * (w / wsum) for w in weights]

    segs = []
    for i in range(count):
        base = vclips[min(i, len(vclips) - 1)]
        seg = _safe_loop(base, seg_durs[i]).set_fps(FPS)
        # subtle zoom to avoid static feel
        try:
            seg = seg.fx(vfx.resize, lambda t: 1.0 + 0.02 * (t / max(seg_durs[i], 0.1)))
        except Exception:
            pass
        segs.append(seg)

    video = concatenate_videoclips(segs, method="compose") if len(segs) > 1 else segs[0]
    video = video.set_audio(narration)

    # Output path (use meta.id if present)
    script_id = (meta or {}).get("id") or os.path.splitext(os.path.basename(audio_path))[0]
    out_path = os.path.join(OUT_DIR, f"{script_id}.mp4")

    # Render
    video.write_videofile(
        out_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate=BITRATE,
        preset="medium",
        threads=4,
        temp_audiofile=os.path.join("output", "temp_audio.m4a"),
        remove_temp=True,
        verbose=True,
        logger=None,
    )

    # Cleanup
    try:
        video.close()
        narration.close()
        for c in vclips:
            try: c.close()
            except Exception: pass
    except Exception:
        pass

    return out_path
