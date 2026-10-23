"""Sarvam AI voice layer for the Sahayak demo: Indian-language speech <-> text.

Only used in the live demo (dashboard 'Try Sahayak' tab), never in the big runs.
Needs SARVAM_API_KEY in .env (sign up at sarvam.ai). Model names are configurable in
.env because Sarvam updates them - check docs.sarvam.ai if a call returns 4xx.
"""
from __future__ import annotations

import base64

import requests

from config import SETTINGS

BASE = "https://api.sarvam.ai"


def available() -> bool:
    return bool(SETTINGS.sarvam_api_key)


def speech_to_text(audio_bytes: bytes, filename: str = "audio.wav", mode: str = "transcribe") -> str:
    """Audio (wav) -> transcript. mode: transcribe | translate (to English) | codemix."""
    r = requests.post(
        f"{BASE}/speech-to-text",
        headers={"api-subscription-key": SETTINGS.sarvam_api_key},
        files={"file": (filename, audio_bytes, "audio/wav")},
        data={"model": SETTINGS.sarvam_stt_model, "mode": mode},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("transcript", "")


def text_to_speech(text: str, language_code: str = "hi-IN") -> bytes:
    """Text -> wav bytes. language_code e.g. hi-IN, ta-IN, kn-IN, mr-IN, en-IN."""
    r = requests.post(
        f"{BASE}/text-to-speech",
        headers={"api-subscription-key": SETTINGS.sarvam_api_key, "Content-Type": "application/json"},
        json={"text": text[:1500], "language_code": language_code,
              "model": SETTINGS.sarvam_tts_model, "speaker": SETTINGS.sarvam_speaker},
        timeout=60,
    )
    r.raise_for_status()
    audios = r.json().get("audios", [])
    return base64.b64decode("".join(audios)) if audios else b""
