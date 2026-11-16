from io import BytesIO
import wave

import pytest

from app.saas.campaign_audio import render_audio


def wav(samples, width=2, channels=2):
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(8000)
        w.writeframes(b"".join((s + 128 if width == 1 else s).to_bytes(width, "little", signed=width != 1)
                               for s in samples))
    return buf.getvalue()


@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("channel,expected", [
    ("student", [100, 0, -100]), ("agent", [0, 80, -40]), ("both", [50, 40, -70])])
def test_render_keeps_both_speakers_and_timing(width, channel, expected):
    data = wav([100, 0, 0, 80, -100, -40], width)
    with wave.open(BytesIO(render_audio(data, channel)), "rb") as w:
        assert w.getnchannels() == 1 and w.getframerate() == 8000 and w.getnframes() == 3
        raw = w.readframes(3)
        actual = [int.from_bytes(raw[i:i+width], "little", signed=width != 1) - (128 if width == 1 else 0)
                  for i in range(0, len(raw), width)]
        assert actual == expected


def test_mono_original_and_invalid_audio():
    mono = wav([10, 20], channels=1)
    assert render_audio(mono, "both") == mono
    with pytest.raises(ValueError, match="one mixed channel"):
        render_audio(mono, "student")
    stereo = wav([100, 0])
    assert render_audio(stereo, "original") == stereo
    with pytest.raises(ValueError):
        render_audio(b"not wav", "both")
    with pytest.raises(ValueError, match="incomplete"):
        render_audio(stereo[:-1], "both")
