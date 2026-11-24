"""Speech-to-text. Pluggable: GoogleSTT (free web recognizer) by default."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .audio import RATE, normalise


class STT(ABC):
    @abstractmethod
    def transcribe(self, pcm: bytes | None) -> str: ...


VOCABULARY = ["Jarvis", "ChatGPT", "Claude", "Claude Code", "Cursor", "Hermes", "Telegram", "BotFather", "Gmail",
              "Google Calendar", "Notepad", "YouTube", "Spotify", "Wispr Flow", "WSL", "PowerShell"]


class WisprFlowSTT(STT):
    """Wispr Flow speech-to-text API (https://api-docs.wisprflow.ai). Needs WISPR_FLOW_API_KEY.
    Better at names and cleans filler words; falls back to another STT on any failure."""
    URL = "https://platform-api.wisprflow.ai/api/v1/dash/api"

    def __init__(self, api_key: str, fallback: STT | None = None, language: str = "en",
                 dictionary: list[str] | None = None):
        self.api_key, self.fallback, self.language = api_key, fallback, language
        self.dictionary = dictionary or VOCABULARY

    def transcribe(self, pcm):
        if not pcm:
            return ""
        import base64
        import json
        import urllib.request

        import speech_recognition as sr
        wav = sr.AudioData(normalise(pcm), RATE, 2).get_wav_data()
        body = json.dumps({"audio": base64.b64encode(wav).decode(),
                           "properties": {"language": self.language, "app_type": "ai",
                                          "dictionary": self.dictionary}}).encode()
        req = urllib.request.Request(self.URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return (json.loads(r.read()).get("text") or "").strip()
        except Exception as e:
            print(f"[stt] Wispr Flow failed ({type(e).__name__}: {e}); using fallback")
            return self.fallback.transcribe(pcm) if self.fallback else ""


def make_stt() -> STT:
    import os
    google = GoogleSTT()
    key = os.getenv("WISPR_FLOW_API_KEY", "").strip()
    if key:
        print("[stt] using Wispr Flow (Google as fallback)")
        return WisprFlowSTT(key, fallback=google)
    return google


class GoogleSTT(STT):
    def __init__(self, language: str = "en-US"):
        import speech_recognition as sr
        self.sr, self.language = sr, language
        self.r = sr.Recognizer()

    def transcribe(self, pcm):
        if not pcm:
            return ""
        audio = self.sr.AudioData(normalise(pcm), RATE, 2)
        try:
            return self.r.recognize_google(audio, language=self.language)
        except self.sr.UnknownValueError:
            return ""
        except self.sr.RequestError as e:
            print(f"[stt] service error: {e}")
            return ""
