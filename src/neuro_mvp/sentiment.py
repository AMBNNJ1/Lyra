from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import math
import wave
import audioop


@dataclass
class TextSentiment:
    label: str  # positive | neutral | negative
    compound: float
    pos: float
    neu: float
    neg: float


@dataclass
class AudioSentiment:
    label: str  # e.g., happy/angry/sad/neutral or arousal:high/med/low
    score: float
    details: Dict[str, Any]


def analyze_text_sentiment(text: str) -> TextSentiment:
    """Analyze text sentiment.

    Tries VADER (fast, small). Falls back to neutral when unavailable.
    """
    if not text:
        return TextSentiment(label="neutral", compound=0.0, pos=0.0, neu=1.0, neg=0.0)
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore

        analyzer = SentimentIntensityAnalyzer()
        scores = analyzer.polarity_scores(text)
        comp = scores.get("compound", 0.0)
        label = (
            "positive" if comp >= 0.5 else
            "negative" if comp <= -0.5 else
            "neutral"
        )
        return TextSentiment(
            label=label,
            compound=float(comp),
            pos=float(scores.get("pos", 0.0)),
            neu=float(scores.get("neu", 1.0)),
            neg=float(scores.get("neg", 0.0)),
        )
    except Exception:
        return TextSentiment(label="neutral", compound=0.0, pos=0.0, neu=1.0, neg=0.0)


def _audio_rms_profile(wav_path: str, window_ms: int = 50) -> Dict[str, Any]:
    """Compute a simple RMS energy profile over time for a WAV file.

    Returns mean/variance/max and a per-window series. Assumes PCM WAV.
    """
    with wave.open(wav_path, 'rb') as r:
        nchannels = r.getnchannels()
        sampwidth = r.getsampwidth()
        framerate = r.getframerate()
        nframes = r.getnframes()
        frames = r.readframes(nframes)

    # Convert to mono if needed
    if nchannels != 1:
        try:
            frames = audioop.tomono(frames, sampwidth, 0.5, 0.5)
            nchannels = 1
        except Exception:
            pass

    # Windowing
    samples_per_window = max(int(framerate * (window_ms / 1000.0)), 1)
    bytes_per_sample = sampwidth
    bytes_per_window = samples_per_window * bytes_per_sample
    rms_series: List[float] = []

    idx = 0
    total_len = len(frames)
    while idx + bytes_per_window <= total_len:
        chunk = frames[idx: idx + bytes_per_window]
        try:
            rms_val = audioop.rms(chunk, sampwidth)  # root-mean-square amplitude
        except Exception:
            rms_val = 0
        rms_series.append(float(rms_val))
        idx += bytes_per_window

    if not rms_series:
        rms_series = [0.0]

    mean = sum(rms_series) / len(rms_series)
    var = sum((x - mean) ** 2 for x in rms_series) / max(len(rms_series) - 1, 1)
    std = math.sqrt(var)
    maxv = max(rms_series) if rms_series else 0.0

    # Normalize rough arousal by 16-bit max amplitude
    # Note: This is a heuristic, not calibrated loudness.
    norm_mean = mean / 32768.0
    norm_std = std / 32768.0
    norm_max = maxv / 32768.0

    return {
        "window_ms": window_ms,
        "series": rms_series,
        "mean": mean,
        "std": std,
        "max": maxv,
        "norm_mean": norm_mean,
        "norm_std": norm_std,
        "norm_max": norm_max,
        "framerate": framerate,
    }


def analyze_audio_sentiment(
    wav_path: str,
    engine: str = "auto",  # auto | ser | rms | none
    model_id: Optional[str] = None,
    local_files_only: bool = False,
) -> AudioSentiment:
    """Analyze audio sentiment from a WAV file.

    engine:
    - 'ser': use a speech emotion recognition model via transformers pipeline. Set model_id to a local path to avoid downloads.
    - 'rms': use RMS energy heuristic only (offline-safe).
    - 'auto': try SER unless offline; fallback to RMS.
    - 'none': skip; return neutral.
    """
    eng = (engine or "auto").lower()
    if eng == "none":
        return AudioSentiment(label="neutral", score=0.0, details={})

    def _rms_only() -> AudioSentiment:
        try:
            prof = _audio_rms_profile(wav_path)
            arousal = float(prof.get("norm_mean", 0.0))
            if arousal >= 0.12:
                label = "arousal:high"
            elif arousal >= 0.06:
                label = "arousal:medium"
            else:
                label = "arousal:low"
            return AudioSentiment(label=label, score=arousal, details=prof)
        except Exception:
            return AudioSentiment(label="unknown", score=0.0, details={})

    # Detect offline mode
    offline = str(__import__("os").getenv("HF_HUB_OFFLINE", "")).strip() not in {"", "0", "false", "False", "no", "No"} or \
              str(__import__("os").getenv("TRANSFORMERS_OFFLINE", "")).strip() not in {"", "0", "false", "False", "no", "No"}

    if eng == "rms" or (eng == "auto" and offline):
        return _rms_only()

    # SER path
    try:
        from transformers import pipeline  # type: ignore
        mid = model_id or "superb/hubert-large-superb-er"
        ser = pipeline("audio-classification", model=mid, local_files_only=local_files_only)
        preds = ser(wav_path, top_k=4)
        if isinstance(preds, list) and preds:
            best = max(preds, key=lambda x: float(x.get("score", 0.0)))
            return AudioSentiment(
                label=str(best.get("label", "neutral")),
                score=float(best.get("score", 0.0)),
                details={"topk": preds},
            )
    except Exception:
        # Fall back to RMS without raising
        return _rms_only()

    # If SER unexpectedly yielded nothing
    return _rms_only()


def analyze_combined(text: Optional[str], wav_path: Optional[str]) -> Dict[str, Any]:
    """Return a combined sentiment view (valence from text, arousal from audio)."""
    out: Dict[str, Any] = {}
    if text is not None:
        ts = analyze_text_sentiment(text)
        out["text"] = ts.__dict__
        # Map to valence
        v = 0.0
        if ts.label == "positive":
            v = 1.0
        elif ts.label == "negative":
            v = -1.0
        out["valence"] = v
    if wav_path is not None:
        as_ = analyze_audio_sentiment(wav_path)
        out["audio"] = {
            "label": as_.label,
            "score": as_.score,
            "details": as_.details,
        }
        # Map RMS to arousal in [0,1]
        if "details" in out["audio"] and isinstance(out["audio"]["details"], dict):
            arousal = float(out["audio"]["details"].get("norm_mean", as_.score))
        else:
            arousal = as_.score
        out["arousal"] = max(0.0, min(1.0, arousal))
    return out
