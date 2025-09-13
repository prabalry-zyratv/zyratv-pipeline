# video.py — auto-pick Pexels clips with robust fallbacks (EN/HI/BN)
# - Derives queries from channel + keywords (Hindi/Bengali supported via tiny maps)
# - Tries multiple queries (broad → specific), vertical-first, size=large
# - Downloads the chosen clips (stable on CI) with small retry/cache
# - Falls back to a dark moving solid if zero results
# - Optional caption burn-in stays handled by your workflow (unchanged)

import os, re, time, hashlib, requests, io
from typing import List, Optional, Dict, Tuple
from moviepy.editor import (
    VideoFileClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip, vfx, ColorClip
)

MEDIA_DIR = "input/media_temp"
OUT_DIR   = "output/final"
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(OUT_DIR,   exist_ok=True)

TARGET_W, TARGET_H, FPS = 1080, 1920, 30
BITRATE = "8000k"

# ---------------- Keywords & maps ----------------

STOP_EN = set("""
the and with your that this then have will just like very from into you for are was were been being been of to a in is it on as at by an be or if so but not no do does did can could should would may might our their his her its them they we us i me
""".split())
STOP_HI = set("है और या या/या कि यह वह तुम आप हम मैं हैं के को से एक भी तो पर में फिर अगर क्योंकि लेकिन तथा होकर जब तक तब बाद पहले बिना जैसे कुछ कोई करना करना है की के लिए नहीं".split())
STOP_BN = set("এবং বা যে এই ওই তুমি আপনি আমরা আমি হয় হয়েছে থেকে একটি কিন্তু তাই পরে আগে যদি যখন তবে এবং করেন করা করি করি না হবে".split())

# rough topic → query helpers for HI/BN tokens
TOPIC_MAP = {
    # Hindi keys
    "गणेश": "ganesha idol temple incense sunrise",
    "शिव": "lord shiva temple himalayas incense",
    "कृष्ण": "krishna temple flute peacock",
    "राम": "ram mandir temple diyas",
    "तंत्र": "tantra ritual candles incense night",
    "भूत": "haunted house night fog forest",
    "नौकरी": "interview office resume corporate",
    "रिज्यूमे": "resume office laptop interview",
    "ध्यान": "meditation temple candles incense",
    # Bengali keys
    "গণেশ": "ganesha idol temple incense",
    "শিব": "lord shiva temple himalayas",
    "কৃষ্ণ": "krishna temple flute",
    "তন্ত্র": "tantra ritual candles night",
    "ভূত": "haunted house fog forest night",
    "চাকরি": "interview office resume corporate",
    "রিজিউমে": "resume office laptop interview",
    "ধ্যান": "meditation temple candles",
}

FAMILY_DEFAULT = {
    "HM": "hindu temple sunrise incense clouds",
    "HT": "night forest fog moonlight candle ritual",
    "MJ": "office laptop city skyline night bokeh",
}

GENERIC_FALLBACKS = [
    "nature landscape sunrise mist",
    "abstract motion background particles",
    "city bokeh lights night"
]

# ---------------- Utilities ----------------

def _verticalize(clip: VideoFileClip) -> VideoFileClip:
    c = clip.resize(height=TARGET_H)
    if c.w < TARGET_W:
        c = clip.resize(width=TARGET_W)
    x1 = max(0, (c.w - TARGET_W) / 2)
    return c.crop(x1=x1, y1=0, x2=x1 + TARGET_W, y2=TARGET_H)

def _safe_loop(clip: VideoFileClip, duration: float) -> VideoFileClip:
    if duration <= 0.1: duration = 0.1
    try:
        return clip.fx(vfx.loop, duration=duration)
    except Exception:
        return clip.set_duration(duration)

def _paragraphs(txt: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", (txt or "").strip()) if p.strip()]
    return paras if paras else [txt.strip()]

def _words(txt: str) -> List[str]:
    # unicode-aware words (letters only, no digits/underscore)
    return re.findall(r"[^\W\d_]+", txt.lower(), flags=re.UNICODE)

def _top_keywords(txt: str, stop: set, k: int = 6) -> List[str]:
    freq = {}
    for w in _words(txt):
        if w in stop or len(w) < 3:
            continue
        freq[w] = freq.get(w, 0) + 1
    return [w for w,_ in sorted(freq.items(), key=lambda x: (-x[1], -len(x[0])))][:k]

def _family_code(channel_code: Optional[str]) -> str:
    if not channel_code:
        return ""
    return channel_code.split("-", 1)[0].upper()

def _auto_queries(script_text: str, meta: Optional[Dict]) -> List[str]:
    """
    Build a prioritized list of Pexels queries:
    1) explicit image_query (if present)
    2) family default (HM/HT/MJ)
    3) mapped HI/BN topic words → english phrases
    4) top keywords mixed with family anchors
    5) generic fallbacks
    """
    q = []
    if meta and meta.get("image_query"):
        q.append(str(meta["image_query"]).strip())

    fam = _family_code((meta or {}).get("channel_code", ""))
    if fam in FAMILY_DEFAULT:
        q.append(FAMILY_DEFAULT[fam])

    # Try mapped Indic tokens to English phrases
    for w in _words(script_text):
        if w in TOPIC_MAP:
            q.append(TOPIC_MAP[w])

    # Language stopwords
    lang = (meta or {}).get("lang", "").lower()
    stop = STOP_EN
    if lang == "hi":
        stop = STOP_HI | STOP_EN
    elif lang == "bn":
        stop = STOP_BN | STOP_EN

    # Mix top keywords into family-themed searches
    kws = _top_keywords(script_text, stop, k=6)
    if kws:
        anchors = {
            "HM": ["temple", "incense", "sunrise", "saffron"],
            "HT": ["night", "forest", "fog", "moonlight"],
            "MJ": ["office", "city", "laptop", "skyline"],
        }.get(fam, ["cinematic", "portrait"])
        # make 3 variations max
        for i in range(min(3, len(kws))):
            q.append(" ".join((anchors[i % len(anchors)], kws[i])))

    # generic safeties
    q.extend(GENERIC_FALLBACKS)

    # dedupe, keep order
    seen = set(); final = []
    for s in q:
        s2 = " ".join(s.split())
        if s2 and s2 not in seen:
            seen.add(s2); final.append(s2)
    return final

# ---------------- Pexels fetchers ----------------

def _pexels_search(query: str, per_page: int = 12) -> dict:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return {"ok": False, "status": 0, "videos": []}
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={
                "query": query,
                "per_page": per_page,
                "orientation": "portrait",   # vertical-first
                "size": "large",
            },
            headers={"Authorization": key, "User-Agent": "ZyraTV-Pipeline/1.0"},
            timeout=30,
        )
        data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        return {"ok": r.ok, "status": r.status_code, "videos": data.get("videos", [])}
    except Exception:
        return {"ok": False, "status": 0, "videos": []}

def _pick_vertical_urls(videos: List[dict], need: int) -> List[str]:
    urls = []
    for v in videos:
        files = sorted(
            v.get("video_files", []),
            key=lambda f: (f.get("height", 0), f.get("width", 0)),
            reverse=True,
        )
        # pick first vertical-ish file
        for f in files:
            w, h = f.get("width", 0), f.get("height", 0)
            link = f.get("link", "")
            if link and h >= w and link.startswith("http"):
                urls.append(link)
                break
        if len(urls) >= need:
            break
    return urls

def _pexels_pick_multi(queries: List[str], need: int = 3) -> List[str]:
    """
    Try a series of queries until we collect up to `need` vertical clips.
    Includes an automatic 'nature' / 'city' safety pass at the end.
    """
    collected: List[str] = []
    tried = 0
    for q in queries:
        tried += 1
        print(f"🔎 Pexels query[{tried}]={q!r}")
        resp = _pexels_search(q, per_page=max(need*4, 12))
        print(f"   status={resp['status']} videos={len(resp['videos'])}")
        if not resp["ok"]:
            continue
        urls = _pick_vertical_urls(resp["videos"], need=need - len(collected))
        collected.extend(urls)
        if len(collected) >= need:
            break

    if len(collected) < need:
        for fallback in ["nature portrait", "city lights portrait"]:
            print(f"   trying fallback={fallback!r}")
            resp = _pexels_search(fallback, per_page=max(need*3, 9))
            print(f"   status={resp['status']} videos={len(resp['videos'])}")
            if resp["ok"]:
                urls = _pick_vertical_urls(resp["videos"], need=need - len(collected))
                collected.extend(urls)
                if len(collected) >= need:
                    break

    return collected

# ---------------- Download (cache) ----------------

def _url_cache_path(url: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(MEDIA_DIR, f"px_{h}.mp4")

def _download(url: str, dest: str, retries: int = 2) -> bool:
    for attempt in range(retries + 1):
        try:
            with requests.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception as e:
            if attempt == retries:
                print(f"   download failed: {e}")
                return False
            time.sleep(1.0 + attempt)

# ---------------- Main ----------------

def make_video(audio_path: str, script_text: str, meta: Optional[Dict] = None) -> str:
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    narration = AudioFileClip(audio_path)
    total_dur = max(0.1, narration.duration)

    # Build multi-query list and collect candidate URLs
    queries = _auto_queries(script_text, meta)
    need = int(os.getenv("SEGMENTS", "3"))
    urls  = _pexels_pick_multi(queries, need=max(1, need))

    # Prepare background clips (download for stability)
    vclips: List[VideoFileClip] = []
    for url in urls:
        dest = _url_cache_path(url)
        if not os.path.exists(dest):
            print(f"⬇️  downloading clip → {dest}")
            ok = _download(url, dest)
            if not ok:
                continue
        try:
            c = VideoFileClip(dest)
            vclips.append(_verticalize(c))
        except Exception as e:
            print("   open failed:", e)

    # No clips? Use a dark moving solid
    if not vclips:
        base = ColorClip(size=(TARGET_W, TARGET_H), color=(12, 12, 16)).set_fps(FPS)
        vclips = [base]

    # Allocate durations by paragraph weight
    paras = _paragraphs(script_text)
    count = min(len(vclips), max(1, len(paras)))
    weights = [len(p) for p in paras[:count]]
    wsum = sum(weights) or 1.0
    seg_durs = [total_dur * (w/wsum) for w in weights]

    segs = []
    for i in range(count):
        base = vclips[min(i, len(vclips) - 1)]
        seg  = _safe_loop(base, seg_durs[i]).set_fps(FPS)
        # subtle zoom to avoid static feel
        try:
            seg = seg.fx(vfx.resize, lambda t: 1.0 + 0.02 * (t / max(seg_durs[i], 0.1)))
        except Exception:
            pass
        segs.append(seg)

    video = concatenate_videoclips(segs, method="compose") if len(segs) > 1 else segs[0]
    video = video.set_audio(narration)

    script_id = (meta or {}).get("id") or os.path.splitext(os.path.basename(audio_path))[0]
    out_path  = os.path.join(OUT_DIR, f"{script_id}.mp4")

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
        video.close(); narration.close()
        for c in vclips:
            try: c.close()
            except Exception: pass
    except Exception:
        pass

    return out_path
