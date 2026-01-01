from __future__ import annotations

import json
import os
import threading
import uuid as uuid_module
from typing import Dict, Optional

from flask import Flask, request, jsonify, send_from_directory, send_file, Response, g, abort
from pathlib import Path
import sys
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

# Ensure project root is on sys.path when running this file directly
ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.neuro_mvp.web_session import WebAgentSession
from src.neuro_mvp.memory import MemoryClient
# VOICE_MODE_DISABLED: TTS import commented out
# from src.neuro_mvp.tts_kokoro import KokoroTTS
from src.neuro_mvp.clerk_auth import ClerkVerifier, ClerkAuthError
from src.neuro_mvp.characters import (
    Character,
    PREDEFINED_CHARACTERS,
    DEFAULT_CHARACTER_ID,
    get_character_by_id,
    get_predefined_characters,
    generate_custom_character_id,
)
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


load_dotenv()  # ensure OPENAI_BASE_URL, MEM0_BASE_URL, etc.

CLERK = _load_clerk_verifier()
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY")
CLERK_LOGIN_DISABLED = os.getenv("CLERK_LOGIN_DISABLED", "true").lower() in ("true", "1", "yes")

GUEST_MESSAGE_LIMIT = int(os.getenv("GUEST_MESSAGE_LIMIT", "5"))
GUEST_USAGE: Dict[str, int] = {}
_GUEST_USAGE_LOCK = threading.Lock()

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload


@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file upload size limit exceeded."""
    return jsonify({"error": "file_too_large", "max_size": "16MB"}), 413


if not CLERK_PUBLISHABLE_KEY:
    app.logger.warning("CLERK_PUBLISHABLE_KEY env var not set; Clerk authentication will not work.")
SESSIONS: Dict[str, WebAgentSession] = {}
_SESSIONS_LOCK = threading.Lock()
BASE_CONFIG: dict | None = None
# VOICE_MODE_DISABLED: TTS engine globals commented out
# TTS_ENGINE: KokoroTTS | None = None
# _TTS_WARM_STARTED = False
# _TTS_WARM_LOCK = threading.Lock()

# Character data storage
DATA_DIR = ROOT / "data"
USER_CHARACTERS_DIR = DATA_DIR / "user_characters"
UPLOADS_DIR = WEB_DIR / "uploads"

# Image upload settings
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
IMAGE_OUTPUT_SIZE = (512, 512)
UPLOAD_DEBUG = os.getenv("UPLOAD_DEBUG", "false").lower() in ("true", "1", "yes")

# Emotion-to-video state mapping (14 OCC emotions -> 6 video states)
EMOTION_TO_VIDEO_STATE = {
    "joy": "happy",
    "relief": "happy",
    "gratitude": "happy",
    "pride": "happy",
    "distress": "sad",
    "disappointment": "sad",
    "shame": "sad",
    "hope": "anxious",
    "fear": "anxious",
    "anger": "angry",
    "reproach": "angry",
    "frustration": "angry",
    "admiration": "curious",
    "surprise": "curious",
}


def _map_emotion_to_video_state(emotion: str, intensity: float) -> str:
    """Map OCC emotion to video state with intensity threshold."""
    if intensity < 0.15:
        return "neutral"
    return EMOTION_TO_VIDEO_STATE.get(emotion, "neutral")


def _get_video_url(character: Optional[Character], video_state: str) -> str:
    """Get video URL for character and emotion state with fallback."""
    if character is None:
        return f"/assets/nova_{video_state}.mp4"

    video_urls = getattr(character, "video_urls", {}) or {}

    # Try requested state first
    if video_state in video_urls:
        return video_urls[video_state]

    # Fall back to neutral
    if "neutral" in video_urls:
        return video_urls["neutral"]

    # Final fallback to static image (no video)
    return character.image_url


def _ensure_directories() -> None:
    """Create required directories if they don't exist."""
    USER_CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _get_user_data_path(user_id: str) -> Path:
    """Return path to user's character data file."""
    safe_id = _sanitize_user_id(user_id)
    return USER_CHARACTERS_DIR / f"{safe_id}.json"


def load_user_character_data(user_id: str) -> dict:
    """Load user's character data from JSON file."""
    path = _get_user_data_path(user_id)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    # Return default structure
    return {
        "selected_character_id": DEFAULT_CHARACTER_ID,
        "custom_characters": [],
        "onboarding_completed": False,
    }


def save_user_character_data(user_id: str, data: dict) -> None:
    """Save user's character data to JSON file."""
    _ensure_directories()
    path = _get_user_data_path(user_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_user_selected_character(user_id: str) -> Character:
    """Get the user's currently selected character."""
    data = load_user_character_data(user_id)
    char_id = data.get("selected_character_id", DEFAULT_CHARACTER_ID)
    custom_chars = [Character.from_dict(c) for c in data.get("custom_characters", [])]
    char = get_character_by_id(char_id, custom_chars)
    return char or PREDEFINED_CHARACTERS[DEFAULT_CHARACTER_ID]


def _allowed_image_file(filename: str) -> bool:
    """Check if file extension is allowed for image upload."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _process_uploaded_image(file_storage) -> tuple:
    """Process uploaded image: validate, resize, save as JPEG.

    Returns: (image_id, image_url)
    """
    from io import BytesIO
    from PIL import Image, UnidentifiedImageError

    _ensure_directories()

    # Read and validate size
    raw = file_storage.read()
    if not raw:
        raise ValueError("Empty image file")
    size = len(raw)

    if size > MAX_IMAGE_SIZE:
        raise ValueError(f"Image too large. Max size: {MAX_IMAGE_SIZE // (1024 * 1024)}MB")

    # Open with Pillow
    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Invalid or unsupported image file") from exc

    # Convert to RGB (handles PNG transparency, etc.)
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize to 512x512, center crop
    img.thumbnail((IMAGE_OUTPUT_SIZE[0] * 2, IMAGE_OUTPUT_SIZE[1] * 2), Image.Resampling.LANCZOS)

    # Center crop to square
    width, height = img.size
    min_dim = min(width, height)
    left = (width - min_dim) // 2
    top = (height - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))
    img = img.resize(IMAGE_OUTPUT_SIZE, Image.Resampling.LANCZOS)

    # Generate unique filename and save
    image_id = uuid_module.uuid4().hex[:16]
    filename = f"{image_id}.jpg"
    filepath = UPLOADS_DIR / filename
    img.save(filepath, "JPEG", quality=85, optimize=True)

    return image_id, f"/uploads/{filename}"


def _get_user_id_from_request() -> str:
    """Extract user ID from request (authenticated or guest)."""
    token = _extract_bearer_token()
    if token:
        try:
            claims = CLERK.verify(token)
            return claims.get("sub") or claims.get("user_id") or "default"
        except ClerkAuthError:
            pass

    # Guest user
    guest_id = request.headers.get("X-Guest-Id") or request.cookies.get("__guest_id", "")
    if guest_id:
        return f"guest-{_sanitize_user_id(guest_id)}"
    return "guest-default"


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


def _session_for_user(user_id: str, character: Optional[Character] = None) -> WebAgentSession:
    """Get or create a session for a user+character combination.

    Memory isolation: Each user+character pair gets its own session and memory scope.
    Session key format: {user_id}_{character_id}
    """
    cfg = ensure_base_config()

    # Load character if not provided
    if character is None:
        character = get_user_selected_character(user_id)

    char_id = character.id if character else DEFAULT_CHARACTER_ID
    session_key = f"{user_id}_{char_id}"  # Composite key for isolation

    with _SESSIONS_LOCK:
        sess = SESSIONS.get(session_key)
        if sess is None:
            import copy as _copy

            c2 = _copy.deepcopy(cfg)
            mem_cfg = c2.setdefault("memory", {})
            provider = (mem_cfg.get("provider") or "mem0").lower()
            mem_cfg.setdefault(provider, {})
            mem_cfg[provider]["user_label"] = f"User is {user_id}."

            # Pass composite user_id for memory isolation
            composite_user_id = session_key
            sess = WebAgentSession(c2, user_id=composite_user_id, character=character)
            SESSIONS[session_key] = sess
        return sess


def _refresh_session_character(user_id: str, character: Character) -> WebAgentSession:
    """Get or create an isolated session for user+character combination.

    When a user switches companions, this returns the session for that specific
    user+character pair, providing complete memory and conversation isolation.
    """
    return _session_for_user(user_id, character)


def _resolve_session(increment_guest: bool = False):
    """Return a session for either an authenticated Clerk user or a guest.

    Guest isolation is enforced by:
    1. Using X-Guest-Id header if provided
    2. Falling back to a __guest_id cookie (auto-generated if missing)

    Quotas are enforced for ALL guests, not just those with explicit headers.
    """
    token = _extract_bearer_token()
    guest_id = (request.headers.get("X-Guest-Id") or "").strip()

    if token:
        raw_uid = require_clerk_user()
        session = _session_for_user(raw_uid)
        return session, None, None

    # Check for existing guest cookie if no header provided
    cookie_guest_id = None
    if not guest_id:
        cookie_guest_id = request.cookies.get("__guest_id", "").strip()
        if cookie_guest_id:
            guest_id = cookie_guest_id

    # Generate new guest ID if still missing
    new_guest_id = None
    if not guest_id:
        import uuid
        new_guest_id = f"g-{uuid.uuid4().hex[:16]}"
        guest_id = new_guest_id

    guest_key = _sanitize_user_id(guest_id)
    if not guest_key:
        import uuid
        new_guest_id = f"g-{uuid.uuid4().hex[:16]}"
        guest_id = new_guest_id
        guest_key = _sanitize_user_id(guest_id)

    # Enforce quotas for ALL guests (not just those with explicit headers)
    remaining = None
    if increment_guest:
        with _GUEST_USAGE_LOCK:
            used = GUEST_USAGE.get(guest_key, 0)
            if used >= GUEST_MESSAGE_LIMIT:
                resp = jsonify({"error": "guest_limit_reached"})
                resp.status_code = 429
                resp.headers["X-Guest-Remaining"] = "0"
                return None, None, resp
            used += 1
            GUEST_USAGE[guest_key] = used
            remaining = max(GUEST_MESSAGE_LIMIT - used, 0)
    else:
        with _GUEST_USAGE_LOCK:
            used = GUEST_USAGE.get(guest_key, 0)
            remaining = max(GUEST_MESSAGE_LIMIT - used, 0)

    session_key = f"guest-{guest_key}"
    # _session_for_user handles character loading and creates composite user_id for memory isolation
    session = _session_for_user(session_key)

    # Store new guest ID for response cookie
    g.new_guest_id = new_guest_id

    return session, remaining, None


# VOICE_MODE_DISABLED: TTS helper functions commented out
# def ensure_tts() -> KokoroTTS:
#     global TTS_ENGINE
#     if TTS_ENGINE is None:
#         lang = os.getenv("KOKORO_LANG", "a")
#         voice = os.getenv("KOKORO_VOICE", "af_heart")
#         TTS_ENGINE = KokoroTTS(lang_code=lang, voice=voice)
#     return TTS_ENGINE
#
#
# def _kickoff_tts_warm() -> None:
#     global _TTS_WARM_STARTED
#     if _TTS_WARM_STARTED:
#         return
#     with _TTS_WARM_LOCK:
#         if _TTS_WARM_STARTED:
#             return
#
#         def _run():
#             try:
#                 ensure_tts().warm()
#             except Exception as exc:  # noqa: BLE001
#                 app.logger.warning('Kokoro warm-up failed: %s', exc)
#
#         threading.Thread(target=_run, daemon=True).start()
#         _TTS_WARM_STARTED = True


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
    # VOICE_MODE_DISABLED: TTS warm-up call commented out
    # _kickoff_tts_warm()


@app.route("/api/auth/config", methods=["GET"])
def auth_config():
    return jsonify({
        "publishableKey": CLERK_PUBLISHABLE_KEY,
        "loginDisabled": CLERK_LOGIN_DISABLED,
    })

MAX_CHAT_MESSAGE_LENGTH = int(os.getenv("MAX_CHAT_MESSAGE_LENGTH", "4000"))
# VOICE_MODE_DISABLED: TTS text length limit commented out
# MAX_TTS_TEXT_LENGTH = int(os.getenv("MAX_TTS_TEXT_LENGTH", "2000"))


# ==================== Character Selection API ====================


@app.route("/api/characters", methods=["GET"])
def api_characters():
    """Get all available characters for the current user."""
    user_id = _get_user_id_from_request()
    data = load_user_character_data(user_id)
    predefined = [c.to_dict() for c in get_predefined_characters()]
    custom = data.get("custom_characters", [])

    resp = jsonify({
        "predefined": predefined,
        "custom": custom,
        "selected_id": data.get("selected_character_id", DEFAULT_CHARACTER_ID),
    })
    return _set_guest_cookie(resp)


@app.route("/api/characters/select", methods=["POST"])
def api_characters_select():
    """Select a character for the current session."""
    user_id = _get_user_id_from_request()

    request_data = request.get_json(force=True, silent=True) or {}
    char_id = (request_data.get("character_id") or "").strip()

    if not char_id:
        return jsonify({"error": "character_id required"}), 400

    user_data = load_user_character_data(user_id)
    custom_chars = [Character.from_dict(c) for c in user_data.get("custom_characters", [])]

    character = get_character_by_id(char_id, custom_chars)
    if not character:
        return jsonify({"error": "character_not_found"}), 404

    # Update user data
    user_data["selected_character_id"] = char_id
    user_data["onboarding_completed"] = True
    save_user_character_data(user_id, user_data)

    # Refresh the session with new character
    _refresh_session_character(user_id, character)

    resp = jsonify({"ok": True, "selected": character.to_dict()})
    return _set_guest_cookie(resp)


@app.route("/api/characters/custom", methods=["POST"])
def api_characters_custom():
    """Create a custom character."""
    user_id = _get_user_id_from_request()

    request_data = request.get_json(force=True, silent=True) or {}
    name = (request_data.get("name") or "").strip()[:32]
    persona = (request_data.get("persona") or "").strip()[:500]
    image_id = (request_data.get("image_id") or "").strip()

    if not name:
        return jsonify({"error": "name required"}), 400
    if not persona:
        return jsonify({"error": "persona required"}), 400

    # Determine image_url
    if image_id:
        image_url = f"/uploads/{image_id}.jpg"
        # Verify image exists
        if not (UPLOADS_DIR / f"{image_id}.jpg").exists():
            return jsonify({"error": "image_not_found"}), 404
    else:
        # Use default avatar
        image_url = "/assets/nova_avatar.jpg"

    # Create character
    char_id = generate_custom_character_id()
    character = Character(
        id=char_id,
        name=name,
        persona=persona,
        image_url=image_url,
        is_predefined=False,
        creator_id=user_id,
    )

    # Save to user data
    user_data = load_user_character_data(user_id)
    user_data.setdefault("custom_characters", []).append(character.to_dict())
    save_user_character_data(user_id, user_data)

    resp = jsonify({"ok": True, "character": character.to_dict()})
    return _set_guest_cookie(resp)


@app.route("/api/characters/custom/<char_id>", methods=["PUT"])
def api_characters_custom_update(char_id: str):
    """Update a custom character (only the owner can edit)."""
    user_id = _get_user_id_from_request()

    # Prevent editing predefined characters
    if char_id in PREDEFINED_CHARACTERS:
        return jsonify({"error": "cannot_edit_predefined"}), 403

    user_data = load_user_character_data(user_id)
    custom_chars = user_data.get("custom_characters", [])

    # Find the character
    char_index = None
    for i, c in enumerate(custom_chars):
        if c.get("id") == char_id:
            char_index = i
            break

    if char_index is None:
        return jsonify({"error": "character_not_found"}), 404

    request_data = request.get_json(force=True, silent=True) or {}
    name = (request_data.get("name") or "").strip()[:32]
    persona = (request_data.get("persona") or "").strip()[:500]
    image_id = (request_data.get("image_id") or "").strip()

    # Update fields if provided
    if name:
        custom_chars[char_index]["name"] = name
    if persona:
        custom_chars[char_index]["persona"] = persona
    if image_id:
        image_url = f"/uploads/{image_id}.jpg"
        if not (UPLOADS_DIR / f"{image_id}.jpg").exists():
            return jsonify({"error": "image_not_found"}), 404
        custom_chars[char_index]["image_url"] = image_url

    user_data["custom_characters"] = custom_chars
    save_user_character_data(user_id, user_data)

    # Refresh session if this is the selected character
    if user_data.get("selected_character_id") == char_id:
        character = Character.from_dict(custom_chars[char_index])
        _refresh_session_character(user_id, character)

    resp = jsonify({"ok": True, "character": custom_chars[char_index]})
    return _set_guest_cookie(resp)


@app.route("/api/characters/custom/<char_id>", methods=["DELETE"])
def api_characters_custom_delete(char_id: str):
    """Delete a custom character (only the owner can delete)."""
    user_id = _get_user_id_from_request()

    # Prevent deleting predefined characters
    if char_id in PREDEFINED_CHARACTERS:
        return jsonify({"error": "cannot_delete_predefined"}), 403

    user_data = load_user_character_data(user_id)
    custom_chars = user_data.get("custom_characters", [])

    # Find and remove the character
    original_len = len(custom_chars)
    custom_chars = [c for c in custom_chars if c.get("id") != char_id]

    if len(custom_chars) == original_len:
        return jsonify({"error": "character_not_found"}), 404

    user_data["custom_characters"] = custom_chars

    # If deleted character was selected, switch to default
    if user_data.get("selected_character_id") == char_id:
        user_data["selected_character_id"] = DEFAULT_CHARACTER_ID
        default_char = PREDEFINED_CHARACTERS[DEFAULT_CHARACTER_ID]
        _refresh_session_character(user_id, default_char)

    save_user_character_data(user_id, user_data)

    resp = jsonify({"ok": True, "deleted_id": char_id})
    return _set_guest_cookie(resp)


@app.route("/api/characters/upload-image", methods=["POST", "OPTIONS"])
def api_characters_upload_image():
    """Upload a character avatar image."""
    # Handle CORS preflight for custom headers
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Guest-Id"
        return resp

    if "image" not in request.files:
        return jsonify({"error": "no image file"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "no selected file"}), 400

    if not file.filename or not _allowed_image_file(file.filename):
        return jsonify({"error": "invalid file type", "allowed": list(ALLOWED_IMAGE_EXTENSIONS)}), 400

    try:
        image_id, image_url = _process_uploaded_image(file)
        resp = jsonify({"ok": True, "image_id": image_id, "image_url": image_url})
        return _set_guest_cookie(resp)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Image upload failed")
        payload = {"error": "upload_failed"}
        if UPLOAD_DEBUG:
            payload["detail"] = str(e)
        return jsonify(payload), 500


@app.route("/api/characters/<char_id>/videos", methods=["GET"])
def api_character_videos(char_id: str):
    """Return all video URLs for a character for preloading."""
    user_id = _get_user_id_from_request()
    user_data = load_user_character_data(user_id)
    custom_chars = [Character.from_dict(c) for c in user_data.get("custom_characters", [])]

    character = get_character_by_id(char_id, custom_chars)
    if not character:
        return jsonify({"error": "character_not_found"}), 404

    video_urls = getattr(character, "video_urls", {}) or {}
    return _set_guest_cookie(jsonify({
        "character_id": char_id,
        "videos": video_urls,
        "fallback_image": character.image_url,
    }))


@app.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Check if user has completed onboarding."""
    user_id = _get_user_id_from_request()
    data = load_user_character_data(user_id)
    resp = jsonify({
        "completed": data.get("onboarding_completed", False),
        "selected_character_id": data.get("selected_character_id", DEFAULT_CHARACTER_ID),
    })
    return _set_guest_cookie(resp)


@app.route("/uploads/<filename>")
def serve_upload(filename: str):
    """Serve uploaded character images."""
    safe_filename = secure_filename(filename)
    filepath = UPLOADS_DIR / safe_filename
    if not filepath.exists() or not filepath.is_file():
        abort(404)
    return send_file(str(filepath))


def _set_guest_cookie(resp):
    """Set __guest_id cookie if a new guest ID was generated."""
    new_guest_id = getattr(g, "new_guest_id", None)
    if new_guest_id:
        resp.set_cookie(
            "__guest_id",
            new_guest_id,
            max_age=60 * 60 * 24 * 365,  # 1 year
            httponly=True,
            samesite="Lax",
            secure=request.is_secure,
        )
    return resp


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("message") or "").strip()

    if len(text) > MAX_CHAT_MESSAGE_LENGTH:
        return jsonify({"error": "message_too_long", "max_length": MAX_CHAT_MESSAGE_LENGTH}), 400

    session, remaining, error_resp = _resolve_session(increment_guest=bool(text))
    if error_resp is not None:
        return error_resp
    if session is None:
        abort(401, description="Unable to resolve user session")

    res = session.chat(text)
    resp = jsonify(res)
    if remaining is not None:
        resp.headers["X-Guest-Remaining"] = str(remaining)
    return _set_guest_cookie(resp)


@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("message") or "").strip()

    session, remaining, error_resp = _resolve_session(increment_guest=bool(text))
    if error_resp is not None:
        return error_resp
    if session is None:
        abort(401, description="Unable to resolve user session")

    # Capture new_guest_id before the generator runs (g context may not persist)
    new_guest_id = getattr(g, "new_guest_id", None)

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
    if remaining is not None:
        headers["X-Guest-Remaining"] = str(remaining)
    resp = Response(gen(), mimetype="text/event-stream", headers=headers)
    if new_guest_id:
        resp.set_cookie(
            "__guest_id",
            new_guest_id,
            max_age=60 * 60 * 24 * 365,  # 1 year
            httponly=True,
            samesite="Lax",
            secure=request.is_secure,
        )
    return resp


@app.route("/api/continuous", methods=["POST"])
def api_continuous():
    session, _, error_resp = _resolve_session()
    if error_resp is not None:
        return error_resp
    if session is None:
        abort(401, description="Unable to resolve user session")
    data = request.get_json(force=True, silent=True) or {}
    enable = bool(data.get("enable", True))
    if enable:
        session.start_continuous()
    else:
        session.stop_continuous()
    return _set_guest_cookie(jsonify({"ok": True, "enabled": enable}))


@app.route("/api/history", methods=["GET"])
def api_history():
    session, _, error_resp = _resolve_session()
    if error_resp is not None:
        return error_resp
    if session is None:
        abort(401, description="Unable to resolve user session")
    msgs = session.truncated_history()
    return _set_guest_cookie(jsonify({"messages": msgs, "count": len(msgs)}))


@app.route("/api/emotion", methods=["GET"])
def api_emotion():
    session, _, error_resp = _resolve_session()
    if error_resp is not None:
        return error_resp
    if session is None:
        abort(401, description="Unable to resolve user session")
    try:
        ee = getattr(session, "ee", None)
        character = getattr(session, "character", None)

        if ee is None:
            video_state = "neutral"
            video_url = _get_video_url(character, video_state)
            return _set_guest_cookie(jsonify({
                "primary": "neutral",
                "intensity": 0.0,
                "levels": {},
                "reason": "",
                "videoState": video_state,
                "videoUrl": video_url,
            }))

        name, inten = ee.state.primary()
        video_state = _map_emotion_to_video_state(name, inten)
        video_url = _get_video_url(character, video_state)

        return _set_guest_cookie(jsonify({
            "primary": name,
            "intensity": float(inten),
            "levels": ee.state.levels,
            "reason": ee.state.last_reason,
            "videoState": video_state,
            "videoUrl": video_url,
        }))
    except Exception:  # noqa: BLE001
        return _set_guest_cookie(jsonify({
            "primary": "neutral",
            "intensity": 0.0,
            "levels": {},
            "reason": "",
            "videoState": "neutral",
            "videoUrl": "/assets/nova_neutral.mp4",
        }))


# VOICE_MODE_DISABLED: /api/tts endpoint commented out
# @app.route("/api/tts", methods=["POST"])
# def api_tts():
#     token = _extract_bearer_token()
#     if token:
#         require_clerk_user()
#     else:
#         # Use _resolve_session logic to identify guest (header or cookie)
#         # This doesn't increment quota but validates guest identity
#         session, _, error_resp = _resolve_session(increment_guest=False)
#         if error_resp is not None:
#             return error_resp
#         if session is None:
#             abort(401, description="Unable to resolve user session")
#
#     data = request.get_json(force=True, silent=True) or {}
#     text = (data.get("text") or "").strip()
#     voice = (data.get("voice") or os.getenv("KOKORO_VOICE", "af_heart")).strip()
#     if not text:
#         return jsonify({"error": "no_text"}), 400
#     if len(text) > MAX_TTS_TEXT_LENGTH:
#         return jsonify({"error": "text_too_long", "max_length": MAX_TTS_TEXT_LENGTH}), 400
#
#     cfg = ensure_base_config()
#     tts_provider = (cfg.get("tts", {}).get("provider") or "kokoro").lower()
#
#     try:
#         if tts_provider == "runpod":
#             # Use RunPod serverless TTS
#             from src.neuro_mvp.runpod_client import RunPodTTSClient, RunPodTTSConfig
#             tts_cfg = cfg.get("tts", {})
#             endpoint_id = tts_cfg.get("runpod_endpoint_id") or os.getenv("RUNPOD_TTS_ENDPOINT", "")
#             client = RunPodTTSClient(RunPodTTSConfig(
#                 endpoint_id=endpoint_id,
#                 api_key=os.getenv("RUNPOD_API_KEY"),
#                 voice=voice,
#             ))
#             data_bytes = client.synthesize(text, voice)
#         else:
#             # Use local Kokoro TTS
#             from tempfile import mkstemp
#             import os as _os
#
#             tts = ensure_tts()
#             if voice and getattr(tts, "voice", None) != voice:
#                 tts = KokoroTTS(lang_code=os.getenv("KOKORO_LANG", "a"), voice=voice)
#             fd, tmp_path = mkstemp(suffix=".wav")
#             _os.close(fd)
#             try:
#                 tts.synthesize_to_wav(text, tmp_path)
#                 with open(tmp_path, "rb") as f:
#                     data_bytes = f.read()
#             finally:
#                 try:
#                     _os.remove(tmp_path)
#                 except Exception:  # noqa: BLE001
#                     pass
#
#         headers = {"Cache-Control": "no-store", "Content-Disposition": "inline; filename=tts.wav"}
#         resp = Response(data_bytes, mimetype="audio/wav", headers=headers)
#         return _set_guest_cookie(resp)
#     except Exception as exc:  # noqa: BLE001
#         resp = jsonify({
#             "error": "synthesis_failed",
#             "message": f"TTS failed: {exc}",
#         })
#         resp.status_code = 500
#         return _set_guest_cookie(resp)


@app.route("/")
def index():
    web_dir = WEB_DIR
    return send_from_directory(str(web_dir), "index.html")


# VOICE_MODE_DISABLED: /voice route commented out
# @app.route("/voice")
# def voice_mode():
#     web_dir = WEB_DIR
#     return send_from_directory(str(web_dir), "voice.html")


@app.route("/favicon.ico")
def favicon():
    """Serve favicon to avoid 404 errors"""
    web_dir = WEB_DIR
    return send_from_directory(str(web_dir / "lyra"), "favicon.svg", mimetype="image/svg+xml")


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
