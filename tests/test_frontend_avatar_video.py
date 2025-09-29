import re
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def extract_section(source: str, start: str, end: str) -> str:
    start_idx = source.index(start) + len(start)
    end_idx = source.index(end, start_idx)
    return source[start_idx:end_idx]


def test_chat_avatar_uses_idle_video():
    html = read('web/index.html')
    match = re.search(r'<video[^>]+id="avatarVideo"[^>]+>', html)
    assert match, 'avatar video element missing on chat page'
    assert '/assets/nova_video.mp4' in match.group(0), 'chat avatar should idle with nova_video.mp4'
    assert 'avatarFallback' not in html, 'chat markup should not include fallback image'


def test_chat_start_talking_keeps_idle_clip():
    html = read('web/index.html')
    section = extract_section(html, 'function startTalking(){', 'function stopTalking(){')
    assert "vid.src = '/assets/nova_video.mp4';" in section
    assert 'vid.loop = true;' in section


def test_chat_stop_talking_is_no_op():
    html = read('web/index.html')
    section = extract_section(html, 'function stopTalking(){', '    async function fetchEmotion')
    assert "vid.removeAttribute('data-state');" in section
    assert "vid.src = '/assets/nova_video.mp4';" in section


def test_voice_mode_uses_only_videos():
    html = read('web/voice.html')
    video_match = re.search(r'<video[^>]+id="voiceVideo"[^>]+>', html)
    assert video_match, 'voice mode should render video avatar'
    assert '/assets/nova_video.mp4' in video_match.group(0)
    assert 'playsinline' in video_match.group(0)
    assert 'voiceFallback' not in html


def test_voice_set_avatar_talking_keeps_idle_video():
    html = read('web/voice.html')
    section = extract_section(html, 'function setAvatarTalking(on) {', 'async function sendToAgent(')
    assert "avatarVideo.src = '/assets/nova_video.mp4';" in section
    assert 'avatarVideo.loop = true;' in section


def test_voice_set_avatar_talking_invocation_present():
    html = read('web/voice.html')
    assert 'setAvatarTalking(' in html
