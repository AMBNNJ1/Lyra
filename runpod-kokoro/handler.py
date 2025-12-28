"""RunPod Serverless handler for Kokoro TTS.

Deploy this to RunPod as a custom serverless endpoint.
See: https://docs.runpod.io/serverless/workers/handlers/overview
"""
from __future__ import annotations

import base64
import io
import wave

import numpy as np
import runpod

# Global pipeline - initialized once on worker startup
_pipeline = None


def get_pipeline():
    """Lazy-load the Kokoro pipeline (expensive, do once per worker)."""
    global _pipeline
    if _pipeline is None:
        from kokoro import KPipeline
        _pipeline = KPipeline(lang_code="a")
    return _pipeline


def handler(event: dict) -> dict:
    """Process a TTS request.

    Input:
        {
            "input": {
                "text": "Hello world",
                "voice": "af_heart",       # optional, default af_heart
                "sample_rate": 24000       # optional, default 24000
            }
        }

    Output:
        {
            "audio_base64": "<base64 WAV data>",
            "sample_rate": 24000,
            "format": "wav"
        }
    """
    try:
        inp = event.get("input", {})
        text = inp.get("text", "")
        voice = inp.get("voice", "af_heart")
        sample_rate = int(inp.get("sample_rate", 24000))

        if not text.strip():
            return {"error": "No text provided"}

        pipe = get_pipeline()
        pieces: list[np.ndarray] = []

        for _, _, audio in pipe(text, voice=voice):
            arr = np.asarray(audio, dtype=np.float32)
            if arr.ndim > 1:
                arr = arr.mean(axis=-1)
            pieces.append(arr)

        if not pieces:
            return {"error": "No audio generated"}

        # Concatenate and convert to 16-bit PCM
        audio_cat = np.concatenate(pieces, axis=0)
        audio_i16 = np.clip(audio_cat, -1.0, 1.0)
        audio_i16 = (audio_i16 * 32767.0).astype(np.int16)

        # Write WAV to bytes
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)  # 16-bit
            w.setframerate(sample_rate)
            w.writeframes(audio_i16.tobytes())
        buf.seek(0)

        return {
            "audio_base64": base64.b64encode(buf.read()).decode("utf-8"),
            "sample_rate": sample_rate,
            "format": "wav",
        }

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
