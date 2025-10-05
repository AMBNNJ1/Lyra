"""Common utility functions for the Neuro MVP system."""

import re
import sys
from typing import Optional


def safe_print(text: str) -> None:
    """Safely print text, handling encoding issues on Windows."""
    try:
        print(text)
    except Exception:
        try:
            sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))
        except Exception:
            pass


def sanitize_user_id(user_id: str) -> str:
    """Sanitize user ID to create a safe slug."""
    if not user_id:
        return "default"
    
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", user_id).strip("-").lower()
    return slug or "default"


def extract_favorite_category(question: str) -> Optional[str]:
    """Extract favorite category from a question like 'what's my favorite X?'"""
    if not question:
        return None
    
    question = question.strip().lower()
    match = re.search(r"what(?:'s| is)?\s+my\s+favorite\s+([a-z][a-z \-]{1,32})\??", question)
    
    if not match:
        return None
    
    category = (match.group(1) or "").strip().strip(" .,!")
    return category if category else None


def safe_get(dictionary: dict, *keys, default=None):
    """Safely get nested dictionary values."""
    current = dictionary
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def truncate_text(text: str, max_length: int = 4000) -> str:
    """Truncate text to maximum length."""
    if not text or len(text) <= max_length:
        return text
    return text[:max_length]


def is_empty_or_whitespace(text: Optional[str]) -> bool:
    """Check if text is empty or contains only whitespace."""
    return not text or not text.strip()
