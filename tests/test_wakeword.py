"""Wake word: the single word "Jarvis" via the offline Vosk spotter. Uses synthetic speech (needs internet for
edge-tts); skipped when the model or network isn't available."""
import asyncio
import os

import aiohttp
import numpy as np
import pytest

from jarvis_os.voice.audio import CHUNK, VOSK_MODEL, WordSpotter

pytestmark = pytest.mark.skipif(not VOSK_MODEL.exists(), reason="Vosk model not downloaded")


def synth(text: str, voice: str) -> np.ndarray:
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    import tempfile

    import edge_tts
    import pygame
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=16000, size=-16, channels=1)
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    asyncio.run(edge_tts.Communicate(text, voice).save(path))
    snd = pygame.mixer.Sound(path)
    arr = pygame.sndarray.array(snd)
    del snd
    os.remove(path)
    pcm = (arr[:, 0] if arr.ndim == 2 else arr).astype(np.int16)    # mixer may be stereo: take one channel
    return np.concatenate([np.zeros(8000, np.int16), pcm, np.zeros(16000, np.int16)])


def spotted(spotter, pcm) -> bool:
    hit = False
    for i in range(0, len(pcm) - CHUNK, CHUNK):
        hit |= spotter.feed(pcm[i:i + CHUNK].tobytes())
    return hit


@pytest.fixture(scope="module")
def spotter():
    return WordSpotter()


@pytest.mark.parametrize("voice", ["en-GB-RyanNeural", "en-US-GuyNeural", "en-IN-PrabhatNeural"])
def test_name_alone_and_in_sentence(spotter, voice):
    try:
        for phrase in ("Jarvis.", "Jarvis, what time is it?"):
            assert spotted(spotter, synth(phrase, voice)), phrase
        for phrase in ("Travis.", "The service was good.", "Can you check my email?"):
            assert not spotted(spotter, synth(phrase, voice)), phrase
    except (OSError, aiohttp.ClientError):
        pytest.skip("no network for synthetic speech")
