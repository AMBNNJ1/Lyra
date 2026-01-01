"""VOICE_MODE_DISABLED: This module is not currently in use.
Kokoro TTS engine wrapper - commented out to disable voice mode.
Uncomment imports in server.py and run_agent.py to re-enable.
"""
from __future__ import annotations

import atexit
import importlib
import json
import os
import subprocess
import sys
import threading
import tempfile
import wave
from pathlib import Path
from typing import Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

# Resolve audio post-processing helper dynamically to avoid Pylance missing-import warnings
_audioop = None
for _mod in ("audioop", "audioop_lts"):
    try:
        _audioop = importlib.import_module(_mod)
        break
    except Exception:
        _audioop = None


def _write_audio_segments(pieces: Sequence[np.ndarray], out: Path, sample_rate: int = 24000) -> None:
    """Write concatenated audio segments to a WAV file."""
    if not pieces:
        pieces = [np.zeros((1,), dtype=np.float32)]

    audio_cat = np.concatenate(pieces, axis=0)
    audio_i16 = np.clip(audio_cat, -1.0, 1.0)
    audio_i16 = (audio_i16 * 32767.0).astype(np.int16)

    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(audio_i16.tobytes())

    _ensure_wav_48k_mono(out)


_PY311_CMD: Sequence[str] | None | bool = None
_WORKER_CLIENT: "KokoroWorkerClient | None" = None
_WORKER_LOCK = threading.Lock()


class KokoroWorkerClient:
    """Persistent helper process hosting Kokoro inside Python 3.11."""

    def __init__(self, cmd: Sequence[str]):
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUNBUFFERED", "1")
        root_str = str(ROOT)
        existing_path = env.get("PYTHONPATH")
        env["PYTHONPATH"] = root_str if not existing_path else f"{root_str}{os.pathsep}{existing_path}"
        args = list(cmd) + ["-m", "src.neuro_mvp.tts_kokoro_worker", "--serve"]
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            env=env,
            bufsize=1,
        )
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("failed to start Kokoro worker: pipes unavailable")
        self._io_lock = threading.Lock()
        self._stderr_thread: threading.Thread | None = None
        if self.proc.stderr is not None:
            self._stderr_thread = threading.Thread(target=self._drain_stderr, name="kokoro-worker-stderr", daemon=True)
            self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            try:
                sys.stderr.write("[kokoro-worker] " + line)
            except Exception:
                pass

    def alive(self) -> bool:
        return self.proc.poll() is None

    def synthesize(self, text: str, voice: str, lang_code: str, out_path: Path, sample_rate: int) -> None:
        payload = {
            "cmd": "synthesize",
            "text": text,
            "voice": voice,
            "lang": lang_code,
            "out_path": str(out_path),
            "sample_rate": int(sample_rate),
        }
        message = json.dumps(payload, ensure_ascii=False)
        with self._io_lock:
            if not self.alive():
                raise RuntimeError("Kokoro worker exited")
            assert self.proc.stdin is not None
            self.proc.stdin.write(message + "\n")
            self.proc.stdin.flush()
            assert self.proc.stdout is not None
            while True:
                response = self.proc.stdout.readline()
                if not response:
                    raise RuntimeError("Kokoro worker closed pipe")
                try:
                    data = json.loads(response)
                    break
                except json.JSONDecodeError:
                    sys.stderr.write(f"[kokoro-worker-out] {response}")
                    continue
        if not data.get("ok"):
            raise RuntimeError(str(data.get("error", "unknown worker error")))

    def close(self) -> None:
        if self.proc.stdin:
            try:
                self.proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                self.proc.stdin.flush()
            except Exception:
                pass
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass


def _reset_worker() -> None:
    global _WORKER_CLIENT
    client = _WORKER_CLIENT
    _WORKER_CLIENT = None
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _get_worker_client(cmd: Sequence[str]) -> KokoroWorkerClient:
    global _WORKER_CLIENT
    with _WORKER_LOCK:
        if _WORKER_CLIENT and _WORKER_CLIENT.alive():
            return _WORKER_CLIENT
        client = KokoroWorkerClient(cmd)
        _WORKER_CLIENT = client
        return client


atexit.register(_reset_worker)


def _python311_command() -> Sequence[str] | None:
    """Locate a Python 3.11 interpreter for the Kokoro subprocess fallback."""
    global _PY311_CMD
    if _PY311_CMD is False:
        return None
    if _PY311_CMD:
        return _PY311_CMD

    override = os.getenv("KOKORO_PY311") or os.getenv("PYTHON311_EXE")
    candidates: list[Sequence[str]]
    if override:
        candidates = [(override,)]
    else:
        candidates = []
        if os.name == "nt":
            candidates.append(("py", "-3.11"))
        candidates.append(("python3.11",))
        if os.name != "nt":
            candidates.append(("python3", "-3.11"))

    for cand in candidates:
        try:
            subprocess.run(
                list(cand) + ["-c", "import sys"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _PY311_CMD = cand
            return cand
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError:
            continue

    _PY311_CMD = False
    return None


class KokoroTTS:
    """Lightweight wrapper around hexgrad/Kokoro-82M via the `kokoro` package.

    Produces a WAV file and normalizes to 48kHz mono 16-bit PCM for compatibility
    with the rest of the pipeline. Falls back to invoking a Python 3.11 helper
    when the package is unavailable in-process (e.g., Python 3.13 environments).
    """

    def __init__(self, lang_code: str = "a", voice: str = "af_heart") -> None:
        self.lang_code = lang_code
        self.voice = voice
        self.pipeline = None
        self._init_error: Exception | None = None

        try:
            from kokoro import KPipeline  # type: ignore

            self.pipeline = KPipeline(lang_code=lang_code)
        except Exception as exc:  # pragma: no cover - import failure handled later
            self._init_error = exc

    def warm(self) -> None:
        """Pre-initialize backend resources (pipeline or worker)."""
        if self.pipeline is not None:
            # Pipeline already constructed in-process. Nothing else to warm.
            return
        cmd = _python311_command()
        if not cmd:
            return
        try:
            client = _get_worker_client(cmd)
        except Exception:
            return
        try:
            tmp_fd, tmp_name = tempfile.mkstemp(suffix='.wav')
            os.close(tmp_fd)
            tmp_path = Path(tmp_name)
            try:
                client.synthesize('', self.voice, self.lang_code, tmp_path, 24000)
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            # Warm-up failures should not stop the app; worker will retry on-demand.
            _reset_worker()

    def synthesize_to_wav(self, text: str, out_path: str, sample_rate: int = 24000) -> None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if self.pipeline is not None:
            pieces: list[np.ndarray] = []
            for _, _, audio in self.pipeline(text, voice=self.voice):
                arr = np.asarray(audio, dtype=np.float32)
                if arr.ndim > 1:
                    arr = arr.mean(axis=-1)
                pieces.append(arr)
            _write_audio_segments(pieces, out, sample_rate=sample_rate)
            return

        self._synthesize_via_worker(text, out, sample_rate)

    def _synthesize_via_worker(self, text: str, out: Path, sample_rate: int) -> None:
        cmd = _python311_command()
        if not cmd:
            raise RuntimeError(
                "Kokoro package unavailable and no Python 3.11 interpreter found. "
                "Install Kokoro into Python 3.11 or set KOKORO_PY311/PYTHON311_EXE."
            ) from self._init_error

        try:
            client = _get_worker_client(cmd)
        except Exception as exc:
            raise RuntimeError("Failed to launch Kokoro worker") from exc

        try:
            client.synthesize(text, self.voice, self.lang_code, out, sample_rate)
        except Exception as exc:
            _reset_worker()
            raise RuntimeError(f"Kokoro synthesis failed: {exc}") from (self._init_error or exc)

        _ensure_wav_48k_mono(out)


def _ensure_wav_48k_mono(path: Path) -> None:
    try:
        with wave.open(str(path), "rb") as r:
            nchannels = r.getnchannels()
            sampwidth = r.getsampwidth()
            framerate = r.getframerate()
            nframes = r.getnframes()
            frames = r.readframes(nframes)

        # If audioop is unavailable (e.g., Python 3.13), skip conversion.
        if _audioop is None:
            return

        changed = False
        # to mono
        if nchannels != 1:
            frames = _audioop.tomono(frames, sampwidth, 0.5, 0.5)
            nchannels = 1
            changed = True
        # to 48k
        if framerate != 48000:
            frames, _ = _audioop.ratecv(frames, sampwidth, nchannels, framerate, 48000, None)
            framerate = 48000
            changed = True
        # to 16-bit
        if sampwidth != 2:
            frames = _audioop.lin2lin(frames, sampwidth, 2)
            sampwidth = 2
            changed = True
        if not changed:
            return
        with wave.open(str(path), "wb") as w:
            w.setnchannels(nchannels)
            w.setsampwidth(sampwidth)
            w.setframerate(framerate)
            w.writeframes(frames)
    except Exception:
        # Best-effort; don't fail pipeline on audio post-process
        pass
