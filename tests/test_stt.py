"""Wispr Flow adapter: request format and fallback (network mocked)."""
import base64
import json
import urllib.request

from jarvis_os.voice.stt import STT, WisprFlowSTT


class Fixed(STT):
    def transcribe(self, pcm):
        return "fallback text"


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


PCM = (b"\x10\x00\xf0\xff" * 4000)


def test_wispr_request_and_response(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        seen["body"] = json.loads(req.data)
        return FakeResp({"id": "x", "text": "Open ChatGPT please", "detected_language": "en"})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = WisprFlowSTT("k123", fallback=Fixed()).transcribe(PCM)
    assert out == "Open ChatGPT please"
    assert seen["url"].endswith("/api/v1/dash/api") and seen["auth"] == "Bearer k123"
    wav = base64.b64decode(seen["body"]["audio"])
    assert wav[:4] == b"RIFF" and "Jarvis" in seen["body"]["properties"]["dictionary"]


def test_wispr_falls_back_on_error(monkeypatch):
    def boom(req, timeout):
        raise OSError("403 not a partner")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert WisprFlowSTT("bad", fallback=Fixed()).transcribe(PCM) == "fallback text"
