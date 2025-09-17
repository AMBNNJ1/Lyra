from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

from .tts_kokoro import _write_audio_segments


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kokoro helper for Python 3.11 environments.")
    parser.add_argument("--serve", action="store_true", help="Run as a persistent worker and read JSON commands from stdin.")
    parser.add_argument("--text-file", help="Path to UTF-8 text file containing the utterance.")
    parser.add_argument("--voice", default="af_heart", help="Kokoro voice to synthesize with.")
    parser.add_argument("--lang", dest="lang_code", default="a", help="Kokoro language code.")
    parser.add_argument("--out", help="Destination WAV file path.")
    parser.add_argument("--sample-rate", type=int, default=24000, help="Base sample rate before 48k normalization.")
    return parser


def _parse_args() -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.serve:
        missing = [flag for flag, value in (("--text-file", args.text_file), ("--out", args.out)) if not value]
        if missing:
            parser.error(f"{', '.join(missing)} required unless --serve is provided")
    return args


def _respond(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle_synthesis(text: str, voice: str, lang_code: str, out_path: Path, sample_rate: int, cache: Dict[str, Any]) -> Dict[str, Any]:
    text = text or ""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not text.strip():
        _write_audio_segments([], out_path, sample_rate=sample_rate)
        return {"ok": True, "empty": True}

    try:
        from kokoro import KPipeline  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency import error surfaced to caller
        return {"ok": False, "error": f"Kokoro import failed: {exc}"}

    try:
        pipeline = cache.get(lang_code)
        if pipeline is None:
            pipeline = KPipeline(lang_code=lang_code)
            cache[lang_code] = pipeline
        pieces: list[np.ndarray] = []
        for _, _, audio in pipeline(text, voice=voice):
            arr = np.asarray(audio, dtype=np.float32)
            if arr.ndim > 1:
                arr = arr.mean(axis=-1)
            pieces.append(arr)
        _write_audio_segments(pieces, out_path, sample_rate=sample_rate)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"Kokoro synthesis failed: {exc}"}


def serve_loop() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    cache: Dict[str, Any] = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            _respond({"ok": False, "error": f"invalid JSON: {exc}"})
            continue
        cmd = msg.get("cmd", "synthesize")
        if cmd == "shutdown":
            _respond({"ok": True})
            break
        if cmd != "synthesize":
            _respond({"ok": False, "error": f"unknown command: {cmd}"})
            continue
        try:
            text = str(msg.get("text", ""))
            voice = str(msg.get("voice", "af_heart"))
            lang_code = str(msg.get("lang", "a"))
            out_path = Path(msg["out_path"])
            sample_rate = int(msg.get("sample_rate", 24000))
        except Exception as exc:
            _respond({"ok": False, "error": f"invalid payload: {exc}"})
            continue
        result = _handle_synthesis(text, voice, lang_code, out_path, sample_rate, cache)
        _respond(result)
    return 0


def run_once(args: argparse.Namespace) -> int:
    text_path = Path(args.text_file)
    out_path = Path(args.out)
    try:
        text = text_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"Failed to read text: {exc}", file=sys.stderr)
        return 2

    result = _handle_synthesis(text, args.voice, args.lang_code, out_path, args.sample_rate, cache={})
    if not result.get("ok", False):
        print(result.get("error", "unknown error"), file=sys.stderr)
        return 4
    return 0


def main() -> int:
    args = _parse_args()
    if args.serve:
        return serve_loop()
    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
