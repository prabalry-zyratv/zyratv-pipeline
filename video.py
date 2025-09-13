# video.py — serverless-friendly renderer with optional caption burn-in (Linux only)
# - Works on Ubuntu GitHub Actions (no Windows paths, no ImageMagick)
# - Uses 1–3 background clips (paragraph-weighted)
# - PEXELS_API_KEY from env; solid background fallback
# - Can burn captions if BURN_IN_CAPTIONS="1" in workflow env

import os, re, subprocess, textwrap, requests
from typing import List, Optional, Dict
from moviepy.editor import (
    VideoFileClip, AudioFileClip, concatenate_videoclips,
    vfx, ColorClip
)

MEDIA_DIR = "input/media_temp"
OUT_DIR   = "output/final"
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(OUT_DIR,   exist_ok=True)

TARGET_W, TARGET_H, FPS = 1080, 1920, 30
BITRATE = "8000k"

# --------------------- helpers ---------------------

def _verticalize(clip: VideoFileClip) -> VideoFileClip:
    c = clip.resize(height=TARGET_H)
    if c.w < TARGET_W:
        c = clip.resize(width=TARGET_W)
    x1 = max(0, (c.w - TARGET_W) / 2)
    return c.crop(x1=x1, y1=0, x2=x1 + TARGET_W, y2=TARGET_H)

def _safe_loop(clip: VideoFileClip, duration: float) -> VideoFileClip:
    if duration <= 0.1:
        duration = 0.1
    try:
        return clip.fx(vfx.loop, duration=duration)
    except Exception:
        return clip.set_duration(duration)

def _paragraphs(txt: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", (txt or "").strip()) if p.strip()]
    return paras if paras else [txt.strip()]

def _derive_query(script_text: str, meta: Optional[Dict]) -> str:
    if meta and meta.get("image_query"):
        return str(meta["image_query"]).strip()
    code = (meta or {}).get("channel_code", "").upper()
    t = (script_text or "").lower()
    if code.startswith("HM-") or any(k in t for k in ("mytholog","ramayan","mahabharat","krishna","shiva")):
        return "hindu temple sunrise clouds incense"
    if code.startswith("HT-") or any(k in t for k in ("tantra","ritual","haunted","ghost","horror")):
        return "night forest fog moonlight candle ritual"
    if code.startswith("MJ-") or any(k in t for k in ("resume","interview","job","career","cv","hiring")):
        return "office laptop city skyline night bokeh"
    return "abstract motion background particles"

def _pexels_pick(query: str, need: int = 3) -> List[str]:
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key or not query:
        return []
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": max(need*3, 6)},
            headers={"Authorization": api_key},
            timeout=30,
        )
        if not resp.ok:
            return []
        vids, data = [], resp.json()
        for v in data.get("videos", []):
            files = sorted(v.get("video_files", []),
                           key=lambda f: (f.get("height",0), f.get("width",0)),
                           reverse=True)
            for f in files:
                link = f.get("link")
                if link and link.startswith("http"):
                    vids.append(link); break
            if len(vids) >= need:
                break
        return vids
    except Exception:
        return []

def _write_srt(paras: List[str], seg_durs: List[float], srt_path: str, wrap: int = 36):
    def ts(sec: float):
        if sec < 0: sec = 0
        ms = int((sec - int(sec)) * 1000)
        h  = int(sec)//3600
        m  = (int(sec)%3600)//60
        s  = int(sec)%60
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    os.makedirs(os.path.dirname(srt_path), exist_ok=True)
    start = 0.0
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, (p, d) in enumerate(zip(paras, seg_durs), 1):
            end = start + max(d, 0.5)
            lines = textwrap.wrap(p, width=wrap) or [p]
            f.write(f"{i}\n{ts(start)} --> {ts(end)}\n")
            f.write("\n".join(lines) + "\n\n")
            start = end

# --------------------- main ---------------------

def make_video(audio_path: str, script_text: str, meta: Optional[Dict] = None) -> str:
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    narration = AudioFileClip(audio_path)
    total_dur = max(0.1, narration.duration)

    query = _derive_query(script_text, meta)
    need  = int(os.getenv("SEGMENTS", "3"))
    urls  = _pexels_pick(query, need=need)

    vclips: List[VideoFileClip] = []
    for url in urls:
        try:
            c = VideoFileClip(url)
            vclips.append(_verticalize(c))
        except Exception:
            pass
    if not vclips:
        vclips = [ColorClip(size=(TARGET_W, TARGET_H), color=(10,10,14)).set_fps(FPS)]

    paras = _paragraphs(script_text)
    count = min(len(vclips), max(1, len(paras)))
    weights = [len(p) for p in paras[:count]]
    wsum = sum(weights) or 1.0
    seg_durs = [total_dur * (w/wsum) for w in weights]

    segs = []
    for i in range(count):
        base = vclips[min(i, len(vclips)-1)]
        seg  = _safe_loop(base, seg_durs[i]).set_fps(FPS)
        try:
            seg = seg.fx(vfx.resize, lambda t: 1.0 + 0.02 * (t / max(seg_durs[i], 0.1)))
        except Exception:
            pass
        segs.append(seg)

    video = concatenate_videoclips(segs, method="compose") if len(segs) > 1 else segs[0]
    video = video.set_audio(narration)

    script_id = (meta or {}).get("id") or os.path.splitext(os.path.basename(audio_path))[0]
    out_path  = os.path.join(OUT_DIR, f"{script_id}.mp4")
    srt_path  = os.path.join("output", f"{script_id}.srt")  # safe path

    # Write base MP4
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

    # Close clips before optional ffmpeg pass
    try:
        video.close(); narration.close()
        for c in vclips:
            try: c.close()
            except Exception: pass
    except Exception:
        pass

    # Optional hard subtitles
    if os.getenv("BURN_IN_CAPTIONS", "0") == "1":
        _write_srt(paras[:count], seg_durs, srt_path, wrap=36)
        tmp_out = os.path.join(OUT_DIR, f"{script_id}.burn.mp4")
        vf = (
          f"subtitles={srt_path}:"
          "force_style='FontName=DejaVu Sans,Fontsize=28,"
          "OutlineColour=&H000000&,BorderStyle=3,Outline=2,Shadow=0,"
          "Alignment=2,MarginV=60'"
        )
        cmd = ["ffmpeg", "-y", "-i", out_path, "-vf", vf, "-c:a", "copy", tmp_out]
        subprocess.run(cmd, check=True)
        os.replace(tmp_out, out_path)

    return out_path
