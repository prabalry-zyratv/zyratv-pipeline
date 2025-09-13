import os
import random
import requests
import re
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips, TextClip, CompositeVideoClip
from moviepy.config import change_settings
from pydub import AudioSegment
import time

# --- IMPORTANT: Set your binary paths here ---
change_settings({"FFMPEG_BINARY": "C:\\ProgramData\\chocolatey\\lib\\ffmpeg\\tools\\ffmpeg\\bin\\ffmpeg.exe"})
change_settings({"IMAGEMAGICK_BINARY": "C:\\Program Files\\ImageMagick-7.1.2-Q16-HDRI\\magick.exe"})

# ----------------- CONFIG -----------------
# PEXELS API KEY SHOULD NOT BE HARDCODED. USE AN ENVIRONMENT VARIABLE FOR SECURITY.
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY") 
MEDIA_DIR = "input/media_temp/"
FINAL_DIR = "output/final/"

os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)

STOPWORDS = {"the","and","with","your","that","this","then","have","will","just","like","very","from","into","you"}
FALLBACK_KEYWORDS = ["nature", "city", "people", "lifestyle"] # Very general fallbacks

# ----------------- HELPERS -----------------
def extract_keywords(text):
    """
    Extracts a single, high-relevance keyword from text.
    """
    text = re.sub(r"[^a-zA-Z ]", "", text).lower()
    words = text.split()
    
    # Filter out stopwords and short words, then pick the longest one
    keywords = [w for w in words if len(w) > 3 and w not in STOPWORDS]
    if not keywords:
        return random.choice(FALLBACK_KEYWORDS)

    return sorted(keywords, key=len, reverse=True)[0]

def fetch_pexels_video(query):
    """Fetch a single best video for a given query with debugging."""
    print(f"Pexels API Key being used: {PEXELS_API_KEY}")
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=1"
    print(f"🔍 Searching Pexels for: '{query}'")
    
    try:
        response = requests.get(url, headers=headers, timeout=10) # Added a timeout
        print(f"API Response Status Code: {response.status_code}")
        response.raise_for_status() # This will raise an HTTPError for bad responses (4xx or 5xx)
        data = response.json()

        if data.get("videos"):
            video = data["videos"][0]
            files_sorted = sorted(video["video_files"], key=lambda x: x["width"], reverse=True)
            video_url = files_sorted[0]["link"]

            file_path = os.path.join(MEDIA_DIR, f"{query.replace(' ', '_')}_{int(time.time())}.mp4")
            r = requests.get(video_url, stream=True, timeout=10)
            r.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
            print(f"✅ Downloaded video for '{query}'")
            return file_path
        else:
            print(f"⚠️ No results for '{query}' from API. Trying with a generic fallback...")
            fallback_query = random.choice(FALLBACK_KEYWORDS)
            print(f"🔍 Searching Pexels for: '{fallback_query}'")
            url = f"https://api.pexels.com/videos/search?query={fallback_query}&per_page=1"
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Fallback API Response Status Code: {response.status_code}")
            data = response.json()
            if data.get("videos"):
                 video = data["videos"][0]
                 files_sorted = sorted(video["video_files"], key=lambda x: x["width"], reverse=True)
                 video_url = files_sorted[0]["link"]
                 file_path = os.path.join(MEDIA_DIR, f"{fallback_query}_{int(time.time())}.mp4")
                 r = requests.get(video_url, stream=True, timeout=10)
                 r.raise_for_status()
                 with open(file_path, "wb") as f:
                     for chunk in r.iter_content(chunk_size=1024*1024):
                         if chunk:
                             f.write(chunk)
                 print(f"✅ Downloaded video for '{fallback_query}'")
                 return file_path
            else:
                 print(f"⚠️ No results for '{fallback_query}'.")
                 return None

    except requests.exceptions.RequestException as e:
        print(f"⚠️ Failed to make Pexels API request: {e}")
        return None

def split_script(script_text):
    """Split script into meaningful chunks (sentences) and return them."""
    sentences = re.split(r'[.!?]', script_text)
    return [s.strip() for s in sentences if s.strip()]

def get_audio_durations(audio_path, script_chunks):
    """
    Calculates the duration of each script chunk based on the audio.
    """
    full_audio = AudioSegment.from_mp3(audio_path)
    total_duration_ms = len(full_audio)
    
    total_chars = sum(len(chunk) for chunk in script_chunks)
    if total_chars == 0:
        return []
    
    durations = []
    for chunk in script_chunks:
        duration_ms = (len(chunk) / total_chars) * total_duration_ms
        durations.append(duration_ms / 1000) # convert to seconds
    return durations

# ----------------- MAIN FUNCTION -----------------
def make_video(audio_path, script_text):
    """
    Create a 9:16 reel where each sentence of script 
    is matched with its own relevant Pexels video and includes subtitles.
    """
    audio_clip = AudioFileClip(audio_path)
    audio_duration = audio_clip.duration

    # Step 1: split script and get durations
    chunks = split_script(script_text)
    chunk_durations = get_audio_durations(audio_path, chunks)
    
    clips = []
    current_time = 0
    
    # Step 2: fetch relevant video per chunk and add subtitles
    for i, chunk in enumerate(chunks):
        query = extract_keywords(chunk)
        media_file = fetch_pexels_video(query)
        
        if not media_file:
            print(f"⚠️ Skipping chunk '{chunk}' due to no video file.")
            continue
            
        duration = chunk_durations[i]
        
        # Load clip and crop to 9:16
        try:
            clip = VideoFileClip(media_file)
        except Exception as e:
            print(f"⚠️ Could not load video file {media_file}: {e}")
            continue

        # Ensure video is at least as long as the segment
        if clip.duration < duration:
            print(f"⚠️ Video is too short. Looping video to fit duration.")
            clip = concatenate_videoclips([clip] * int(duration / clip.duration + 1))
            
        clip = clip.resize(height=1920)
        clip = clip.crop(width=1080, height=1920,
                         x_center=clip.w//2, y_center=clip.h//2)
        clip = clip.subclip(0, duration)
        
        # Add a subtitle to the video clip
        txt_clip = TextClip(chunk, fontsize=70, color='white', 
                            bg_color='black', stroke_color='black', stroke_width=2,
                            size=(1000, None), method='caption')
        txt_clip = txt_clip.set_position(('center', 'bottom')).set_duration(duration)
        
        final_chunk_clip = CompositeVideoClip([clip, txt_clip])
        final_chunk_clip.set_start(current_time)
        
        clips.append(final_chunk_clip)
        current_time += duration

    if not clips:
        raise Exception("No video clips found for any script chunk")

    # Step 3: concatenate & add audio
    final_clip = concatenate_videoclips(clips).set_audio(audio_clip)

    # Step 4: export
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    output_path = os.path.join(FINAL_DIR, f"{base_name}.mp4")
    
    print("⏳ Rendering final video...")
    final_clip.write_videofile(
        output_path,
        fps=24,
        codec='libx264',
        audio_codec='aac'
    )

    # Cleanup
    final_clip.close()
    audio_clip.close()
    for c in clips:
        c.close()
    for file in os.listdir(MEDIA_DIR):
        os.remove(os.path.join(MEDIA_DIR, file))

    return output_path
