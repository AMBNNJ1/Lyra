from __future__ import annotations

import os
import threading
from typing import Dict

from flask import Flask, request, jsonify, send_from_directory, send_file, Response, g, abort
from pathlib import Path
import sys
from dotenv import load_dotenv

# Ensure project root is on sys.path when running this file directly
ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.neuro_mvp.web_session import WebAgentSession
from src.neuro_mvp.memory import MemoryClient
from src.neuro_mvp.tts_kokoro import KokoroTTS
from src.neuro_mvp.clerk_auth import ClerkVerifier, ClerkAuthError
import yaml


def load_config() -> dict:
    p = Path("config.yaml")
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _load_clerk_verifier() -> ClerkVerifier:
    try:
        return ClerkVerifier.from_env()
    except RuntimeError as exc:  # noqa: BLE001
        raise RuntimeError(
            "Clerk authentication is not configured. Set CLERK_ISSUER and/or CLERK_JWKS_URL env vars."
        ) from exc


load_dotenv()  # ensure QDRANT_URL, QDRANT_API_KEY, OPENAI_BASE_URL, etc.

CLERK = _load_clerk_verifier()
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY")

GUEST_MESSAGE_LIMIT = int(os.getenv("GUEST_MESSAGE_LIMIT", "5"))
GUEST_USAGE: Dict[str, int] = {}
_GUEST_USAGE_LOCK = threading.Lock()

app = Flask(__name__, static_folder="static", static_url_path="/static")
if CLERK_PUBLISHABLE_KEY == "pk_XXX_ADD_REAL_CLERK_PUBLISHABLE_KEY":
    app.logger.warning("CLERK_PUBLISHABLE_KEY env var missing; using placeholder key for Clerk. Replace with your real publishable key.")
SESSIONS: Dict[str, WebAgentSession] = {}
BASE_CONFIG: dict | None = None
TTS_ENGINE: KokoroTTS | None = None
_TTS_WARM_STARTED = False
_TTS_WARM_LOCK = threading.Lock()


def ensure_base_config() -> dict:
    global BASE_CONFIG
    if BASE_CONFIG is None:
        cfg = load_config()
        cfg.setdefault("conversation", {})
        cfg["conversation"]["require_input"] = False
        cfg["conversation"]["autodrive_input_timeout_sec"] = float(os.getenv("WEB_AUTODRIVE_TIMEOUT", "15"))
        cfg["conversation"]["autodrive_assistant_timeout_sec"] = float(os.getenv("WEB_AUTODRIVE_ASSISTANT_TIMEOUT", "5"))
        BASE_CONFIG = cfg
    return BASE_CONFIG


def _sanitize_user_id(uid: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", uid or "").strip("-").lower()
    return slug or "default"


def _session_for_user(user_id: str) -> WebAgentSession:
    cfg = ensure_base_config()
    sess = SESSIONS.get(user_id)
    if sess is None:
        import copy as _copy

        c2 = _copy.deepcopy(cfg)
        mem_cfg = c2.setdefault("memory", {})
        provider = (mem_cfg.get("provider") or "qdrant").lower()
        mem_cfg.setdefault(provider, {})
        mem_cfg[provider]["user_label"] = f"User is {user_id}."
        sess = WebAgentSession(c2)
        SESSIONS[user_id] = sess
    return sess


def ensure_tts() -> KokoroTTS:
    global TTS_ENGINE
    if TTS_ENGINE is None:
        lang = os.getenv("KOKORO_LANG", "a")
        voice = os.getenv("KOKORO_VOICE", "af_heart")
        TTS_ENGINE = KokoroTTS(lang_code=lang, voice=voice)
    return TTS_ENGINE


def _kickoff_tts_warm() -> None:
    global _TTS_WARM_STARTED
    if _TTS_WARM_STARTED:
        return
    with _TTS_WARM_LOCK:
        if _TTS_WARM_STARTED:
            return

        def _run():
            try:
                ensure_tts().warm()
            except Exception as exc:  # noqa: BLE001
                app.logger.warning('Kokoro warm-up failed: %s', exc)

        threading.Thread(target=_run, daemon=True).start()
        _TTS_WARM_STARTED = True


def _extract_bearer_token() -> str | None:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    token = request.headers.get("Clerk-Session-Token")
    if not token:
        token = request.cookies.get("__session")
    return token


def require_clerk_user() -> str:
    token = _extract_bearer_token()
    if not token:
        abort(401, description="Missing Clerk session token")
    try:
        claims = CLERK.verify(token)
    except ClerkAuthError as exc:
        abort(401, description=str(exc))
    user_id = claims.get("sub") or claims.get("user_id")
    if not user_id:
        abort(401, description="Token missing subject")
    g.clerk_claims = claims
    g.clerk_user_id = user_id
    return user_id


@app.before_request
def _before_request() -> None:
    ensure_base_config()
    _kickoff_tts_warm()


@app.route("/api/auth/config", methods=["GET"])
def auth_config():
    return jsonify({"publishableKey": CLERK_PUBLISHABLE_KEY})

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("message") or "").strip()
    token = _extract_bearer_token()
    guest_id = (request.headers.get("X-Guest-Id") or "").strip()

    if token:
        raw_uid = require_clerk_user()
        session = _session_for_user(raw_uid)
        res = session.chat(text)
        return jsonify(res)

    if guest_id:
        guest_key = _sanitize_user_id(guest_id)
        if not guest_key:
            abort(401, description="Invalid guest id")
        with _GUEST_USAGE_LOCK:
            used = GUEST_USAGE.get(guest_key, 0)
            if used >= GUEST_MESSAGE_LIMIT:
                remaining = 0
                allowed = False
            else:
                used += 1
                GUEST_USAGE[guest_key] = used
                remaining = max(GUEST_MESSAGE_LIMIT - used, 0)
                allowed = True

        if not allowed:
            resp = jsonify({"error": "guest_limit_reached"})
            resp.status_code = 429
            resp.headers["X-Guest-Remaining"] = "0"
            return resp

        session_key = f"guest-{guest_key}"
        session = _session_for_user(session_key)
        session.mem.user_id = session_key
        res = session.chat(text)
        resp = jsonify(res)
        resp.headers["X-Guest-Remaining"] = str(remaining)
        return resp

    abort(401, description="Missing Clerk session token or guest id")


@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    raw_uid = require_clerk_user()
    session = _session_for_user(raw_uid)
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("message") or "").strip()

    def gen():
        try:
            for chunk in session.stream_chat(text):  # type: ignore[attr-defined]
                if not isinstance(chunk, str):
                    continue
                payload = {"delta": chunk}
                import json as _json

                yield f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            import json as _json

            err = {"delta": f"(error) {exc}"}
            yield f"data: {_json.dumps(err, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(gen(), mimetype="text/event-stream", headers=headers)


@app.route("/api/continuous", methods=["POST"])
def api_continuous():
    raw_uid = require_clerk_user()
    session = _session_for_user(raw_uid)
    data = request.get_json(force=True, silent=True) or {}
    enable = bool(data.get("enable", True))
    if enable:
        session.start_continuous()
    else:
        session.stop_continuous()
    return jsonify({"ok": True, "enabled": enable})


@app.route("/api/history", methods=["GET"])
def api_history():
    raw_uid = require_clerk_user()
    session = _session_for_user(raw_uid)
    msgs = session.truncated_history()
    return jsonify({"messages": msgs, "count": len(msgs)})


@app.route("/api/emotion", methods=["GET"])
def api_emotion():
    raw_uid = require_clerk_user()
    session = _session_for_user(raw_uid)
    try:
        ee = getattr(session, "ee", None)
        if ee is None:
            return jsonify({"primary": "neutral", "intensity": 0.0, "levels": {}, "reason": ""})
        name, inten = ee.state.primary()
        return jsonify({
            "primary": name,
            "intensity": float(inten),
            "levels": ee.state.levels,
            "reason": ee.state.last_reason,
        })
    except Exception:  # noqa: BLE001
        return jsonify({"primary": "neutral", "intensity": 0.0, "levels": {}, "reason": ""})


@app.route("/api/tts", methods=["POST"])
def api_tts():
    require_clerk_user()
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = (data.get("voice") or os.getenv("KOKORO_VOICE", "af_heart")).strip()
    if not text:
        return jsonify({"error": "no_text"}), 400
    from tempfile import mkstemp
    import os as _os

    try:
        tts = ensure_tts()
        if voice and getattr(tts, "voice", None) != voice:
            tts = KokoroTTS(lang_code=os.getenv("KOKORO_LANG", "a"), voice=voice)
        fd, tmp_path = mkstemp(suffix=".wav")
        _os.close(fd)
        try:
            tts.synthesize_to_wav(text, tmp_path)
            with open(tmp_path, "rb") as f:
                data_bytes = f.read()
        finally:
            try:
                _os.remove(tmp_path)
            except Exception:  # noqa: BLE001
                pass
        headers = {"Cache-Control": "no-store", "Content-Disposition": "inline; filename=tts.wav"}
        return Response(data_bytes, mimetype="audio/wav", headers=headers)
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "error": "synthesis_failed",
            "message": f"Kokoro failed: {exc}",
        }), 500


@app.route("/")
def index():
    web_dir = WEB_DIR
    return send_from_directory(str(web_dir), "index.html")


@app.route("/voice")
def voice_mode():
    web_dir = WEB_DIR
    return send_from_directory(str(web_dir), "voice.html")


@app.route("/web/<path:path>")
def web_assets(path: str):
    web_dir = WEB_DIR
    return send_from_directory(str(web_dir), path)


@app.route("/landing")
def landing():
    web_dir = WEB_DIR
    return send_from_directory(str(web_dir), "landing.html")


@app.route("/<path:filename>")
def web_static(filename: str):
    if "." not in filename:
        abort(404)
    full = (WEB_DIR / filename).resolve()
    try:
        full.relative_to(WEB_DIR)
    except ValueError:
        abort(404)
    if not full.is_file():
        abort(404)
    return send_file(str(full))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "7860")), debug=False)
