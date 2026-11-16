"""Render Sarvam's split stereo recording as an audible mono mix or isolated speaker."""
from io import BytesIO
import wave


def render_audio(content: bytes, channel: str) -> bytes:
    if channel == "original":
        return content
    try:
        with wave.open(BytesIO(content), "rb") as source:
            channels, width, rate = source.getnchannels(), source.getsampwidth(), source.getframerate()
            if channels == 1:
                if channel != "both":
                    raise ValueError("This recording has one mixed channel; individual speakers cannot be separated.")
                return content
            if channels != 2 or width not in (1, 2, 3, 4) or source.getcomptype() != "NONE":
                raise ValueError("Speaker playback is unavailable for this audio format. Download the original recording.")
            frames = source.readframes(source.getnframes())
            if len(frames) != source.getnframes() * channels * width:
                raise ValueError("The recording is incomplete. Try fetching it again.")
        output = bytearray(len(frames) // 2)
        def sample(offset):
            value = int.from_bytes(frames[offset:offset + width], "little", signed=width != 1)
            return value - 128 if width == 1 else value
        for i in range(0, len(frames), width * 2):
            left, right = sample(i), sample(i + width)
            value = left if channel == "student" else right if channel == "agent" else (left + right) // 2
            if width == 1:
                value += 128
            output[i // 2:i // 2 + width] = value.to_bytes(width, "little", signed=width != 1)
        result = BytesIO()
        with wave.open(result, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(width)
            target.setframerate(rate)
            target.writeframes(output)
        return result.getvalue()
    except (wave.Error, EOFError) as exc:
        raise ValueError("This audio cannot be mixed. Try the original recording.") from exc
