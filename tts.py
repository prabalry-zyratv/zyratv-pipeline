# tts.py — multilingual, long-script safe (HI / BN / EN)
import os
import re
import time
import tempfile
from typing import List, Optional

from gtts import gTTS
from pydub import AudioSegment


def _normalize_lang(lang: Optional[str], channel_code: Optional[str]) -> str:
    """
    Map lang/channel_code → gTTS language code.
    Defaults to 'en'. Supports: en, hi, bn.
    """
    if lang:
        l = lang.strip().lower()
        if l in ("en", "hi", "bn"):
            return l

    if channel_code:
        cc = channel_code.strip().upper()
        if cc.endswith("-HI"):
            return "hi"
        if cc.endswith("-BN"):
            return "bn"
        if cc.endswith("-EN"):
            return "en"

    return "en"


def _clean_text(s: str) -> str:
    # Simple normalize; keep punctuation for better TTS prosody
    s = s.replace("\r\n", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", s)


def _sentence_split(s: str) -> List[str]:
    """
    Split text into sentences/paragraph blocks.
    We keep it generous so we don't over-fragment long scripts.
    """
    # First split on blank lines (paragraphs)
    paras = [p.strip() for p in re.split(r"\n\s*\n", s) if p.strip()]
    if not paras:
        paras = [s]

    # Within each paragraph, split lightly on . ! ? (but keep numbers/abbreviations tolerant)
    chunks: List[str] = []
    for p in paras:
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", p)
        for part in parts:
            t = part.strip()
            if t:
                chunks.append(t)
    return chunks


def _chunk_by_limit(sentences: List[str], max_chars: int = 3000) -> List[str]:
    """
    Group sentences so each chunk ≤ max_chars for gTTS stability.
    """
    chunks: List[str] = []
    buf = ""
    for s in sentences:
        # +1 for space/newline
        if len(buf) + len(s) + 1 > max_chars:
            if buf:
                chunks.append(buf.strip())
            buf = s
        else:
            buf = (buf + " " + s).strip()
    if buf:
        chunks.append(buf.strip())
    return chunks


def _speak_chunk(text: str, lang: str, retries: int = 3, backoff: float = 2.0) -> AudioSegment:
    """
    Synthesize one chunk with retries; return as pydub AudioSegment.
    """
    for attempt in range(1, retries + 1):
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name
            # gTTS: set only 'lang'; tld left default for simplicity.
            gTTS(text=text, lang=lang).save(tmp_path)
            seg = AudioSegment.from_mp3(tmp_path)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return seg
        except Exception as e:
            if attempt == retries:
                raise
            time.sleep(backoff * attempt)  # exponential-ish backoff


def text_to_speech(text: str, output_path: str, lang: Optional[str] = None, channel_code: Optional[str] = None):
    """
    Convert text → MP3 using gTTS with basic robustness:
      - auto language from lang or channel_code (EN/HI/BN)
      - splits long scripts into safe chunks
      - concatenates into one MP3
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    norm_lang = _normalize_lang(lang, channel_code)
    cleaned = _clean_text(text)
    sentences = _sentence_split(cleaned)
    chunks = _chunk_by_limit(sentences, max_chars=3000)

    # Synthesize and concatenate
    final = AudioSegment.silent(duration=0)
    for idx, ch in enumerate(chunks, 1):
        seg = _speak_chunk(ch, norm_lang)
        final += seg

    # Export single MP3
    final.export(output_path, format="mp3")
    print(f"🎤 Audio saved ({norm_lang}): {output_path}")
