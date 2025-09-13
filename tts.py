# src/tts.py
# Test Jira integration

import os
from gtts import gTTS

def text_to_speech(text, output_path):
    """
    Converts text to speech using gTTS and saves as MP3.
    
    Args:
        text (str): The script text to convert
        output_path (str): Full path to save the MP3 file
    """
    # Ensure parent folder exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    tts = gTTS(text=text, lang="en")
    tts.save(output_path)
    print(f"🎤 Audio saved: {output_path}")
