from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_text(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_meta_viewport_present_in_chat_and_voice() -> None:
    chat_html = load_text("web/index.html")
    voice_html = load_text("web/voice.html")
    expected_tag = '<meta name="viewport" content="width=device-width, initial-scale=1" />'
    assert expected_tag in chat_html
    assert expected_tag in voice_html


def test_topbar_actions_replaces_inline_styles() -> None:
    chat_html = load_text("web/index.html")
    assert 'class="topbar-actions"' in chat_html
    assert 'style="position:absolute' not in chat_html


def test_responsive_breakpoints_declared() -> None:
    css = load_text("web/styles.css")
    for width in ("980px", "640px", "480px"):
        assert f"@media (max-width: {width})" in css


def test_mobile_block_contains_topbar_rules() -> None:
    css = load_text("web/styles.css")
    mobile_block = re.search(r"@media\s*\(max-width:\s*480px\)\s*\{([^{}]|\{[^{}]*\})*\}", css, re.S)
    assert mobile_block, "Expected a 480px breakpoint block"
    snippet = mobile_block.group(0)
    assert ".topbar-actions" in snippet
    assert "#loginBtn" in snippet
    assert "theme-btn.icon-only" in snippet

def test_mobile_preview_launcher_exists() -> None:
    script_path = PROJECT_ROOT / "tools/run_mobile_preview.py"
    assert script_path.exists(), "Expected mobile preview launcher script to exist"
    script_text = script_path.read_text(encoding="utf-8")
    assert "--window-size" in script_text
    assert "MOBILE_PREVIEW_BROWSER" in script_text
