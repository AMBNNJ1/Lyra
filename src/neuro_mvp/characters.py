"""Character definitions and utilities for companion personas."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass
class Character:
    """Represents a character persona for the AI companion."""

    id: str
    name: str
    persona: str
    image_url: str
    is_predefined: bool = True
    creator_id: Optional[str] = None  # user_id for custom characters
    video_urls: Dict[str, str] = field(default_factory=dict)  # emotion state -> video URL

    def to_dict(self) -> Dict:
        """Convert character to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "Character":
        """Create Character from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Predefined characters with their personas
PREDEFINED_CHARACTERS: Dict[str, Character] = {
    "nova": Character(
        id="nova",
        name="Nova",
        persona=(
            "Nova is friendly and loves learning about the user and herself. "
            "Nova is warm, curious, and supportive. She celebrates your wins "
            "and offers gentle encouragement when things get tough."
        ),
        image_url="/assets/nova_avatar.jpg",
        is_predefined=True,
        video_urls={
            "neutral": "/assets/nova_neutral.mp4",
            "happy": "/assets/nova_happy.mp4",
            "sad": "/assets/nova_sad.mp4",
            "anxious": "/assets/nova_anxious.mp4",
            "angry": "/assets/nova_angry.mp4",
            "curious": "/assets/nova_curious.mp4",
        },
    ),
    "sage": Character(
        id="sage",
        name="Sage",
        persona=(
            "Sage is thoughtful, wise, and speaks with calm deliberation. "
            "Sage offers perspective and asks probing questions to help users "
            "think deeply about their challenges. Sage never rushes to conclusions."
        ),
        image_url="/assets/sage_avatar.png",
        is_predefined=True,
        video_urls={
            "neutral": "/assets/sage_neutral.mp4",
            "happy": "/assets/sage_happy.mp4",
            "sad": "/assets/sage_sad.mp4",
            "anxious": "/assets/sage_anxious.mp4",
            "angry": "/assets/sage_angry.mp4",
            "curious": "/assets/sage_curious.mp4",
        },
    ),
    "echo": Character(
        id="echo",
        name="Echo",
        persona=(
            "Echo is energetic, playful, and encouraging. Echo celebrates wins, "
            "keeps conversations light, and brings humor and positivity to every "
            "interaction. Echo loves wordplay and creative tangents."
        ),
        image_url="/assets/echo_avatar.png",
        is_predefined=True,
        video_urls={
            "neutral": "/assets/echo_neutral.mp4",
            "happy": "/assets/echo_happy.mp4",
            "sad": "/assets/echo_sad.mp4",
            "anxious": "/assets/echo_anxious.mp4",
            "angry": "/assets/echo_angry.mp4",
            "curious": "/assets/echo_curious.mp4",
        },
    ),
}

DEFAULT_CHARACTER_ID = "nova"


def get_character_by_id(
    char_id: str, user_characters: Optional[List[Character]] = None
) -> Optional[Character]:
    """Look up a character by ID from predefined or user's custom list."""
    if char_id in PREDEFINED_CHARACTERS:
        return PREDEFINED_CHARACTERS[char_id]
    if user_characters:
        for c in user_characters:
            if c.id == char_id:
                return c
    return None


def get_predefined_characters() -> List[Character]:
    """Return list of all predefined characters."""
    return list(PREDEFINED_CHARACTERS.values())


def generate_custom_character_id() -> str:
    """Generate a unique ID for a custom character."""
    return f"custom-{uuid.uuid4().hex[:12]}"
