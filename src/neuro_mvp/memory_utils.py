"""Memory-related utility functions."""

import re
from typing import Any, Dict, List, Optional

from .memory import MemoryClient
from .utils import extract_favorite_category


def try_direct_memory_answer(mem: MemoryClient, question: str) -> Optional[str]:
    """Lightweight heuristics for answering 'what's my favorite X?' questions."""
    category = extract_favorite_category(question)
    if not category:
        return None

    # Search for favorite items
    needles = [f"favorite {category}", f"fav {category}"]
    items: List[Dict[str, Any]] = []
    
    for needle in needles:
        try:
            items.extend(mem.find_items(needle, labels=["preferences", "profile", "facts"], limit=24))
        except Exception:
            pass
    
    if not items:
        try:
            items = mem.find_items(category, labels=["preferences", "profile", "facts"], limit=24)
        except Exception:
            items = []

    # Collect text content
    texts: List[str] = []
    try:
        blocks = mem.search("") or []
        for block in blocks:
            if (block.get("label") in {"preferences", "profile", "facts"}) and block.get("value"):
                texts.append(str(block.get("value")))
    except Exception:
        pass
    
    for item in items or []:
        if item.get("text"):
            texts.append(str(item.get("text")))

    # Look for explicit favorite declarations
    candidate_lines = _extract_candidate_lines(texts, category)
    explicit_answer = _find_explicit_favorite(candidate_lines, category)
    if explicit_answer:
        return explicit_answer

    # Look for likes/preferences as potential favorites
    likes_answer = _find_likes_as_favorites(texts, category)
    if likes_answer:
        return likes_answer

    return None


def _extract_candidate_lines(texts: List[str], category: str) -> List[str]:
    """Extract candidate lines that might contain favorite information."""
    candidate_lines: List[str] = []
    banned_prefixes = ("user:", "assistant:", "query:", "title:", "url:", "excerpt:")
    
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or "?" in stripped:
                continue
            
            lowered = stripped.lower()
            if any(lowered.startswith(pref) for pref in banned_prefixes):
                continue
            
            if f"favorite {category}" in lowered or f"fav {category}" in lowered:
                candidate_lines.append(stripped)
    
    return candidate_lines


def _find_explicit_favorite(candidate_lines: List[str], category: str) -> Optional[str]:
    """Find explicit favorite declarations."""
    rx_explicit = re.compile(rf"favorite\s+{re.escape(category)}\s*(?:is|are|:)\s*([^\n\.;,]+)", re.I)
    
    for line in candidate_lines:
        matches = list(rx_explicit.finditer(line))
        if not matches:
            continue
        
        value = (matches[-1].group(1) or "").strip()
        value = re.sub(
            rf"^(?:user['']s|my|the user['']s)\s+favorite\s+{re.escape(category)}\s*(?:is|are|:)\s*",
            "", value, flags=re.I
        ).strip(" .,!")
        
        if value and not any(value.lower().startswith(prefix) for prefix in ("what", "who", "where", "when", "why", "how")):
            return f"You told me your favorite {category} is {value}."
    
    return None


def _find_likes_as_favorites(texts: List[str], category: str) -> Optional[str]:
    """Find likes/preferences that might indicate favorites."""
    rx_like = re.compile(rf"\b(?:i\s+)?(?:like|love|enjoy|prefer)\s+([^\n\.;,]+)", re.I)
    likes: List[str] = []
    
    for text in texts:
        if category in text.lower():
            like_match = rx_like.search(text)
            if like_match:
                candidate = (like_match.group(1) or "").strip().strip(" .,!")
                if candidate and candidate.lower() != category:
                    likes.append(candidate)
    
    # Remove duplicates while preserving order
    unique_likes: List[str] = []
    seen: set[str] = set()
    for value in likes:
        lowered = value.lower()
        if lowered not in seen:
            seen.add(lowered)
            unique_likes.append(value)
    
    if unique_likes:
        if len(unique_likes) == 1:
            return f"You've said you like {unique_likes[0]}. Is that your favorite {category}?"
        return f"You've mentioned liking {', '.join(unique_likes[:3])}. Do you have one favorite {category}?"
    
    return None
