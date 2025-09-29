from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class AutoMemoryConfig:
    enable: bool = True
    importance_threshold: int = 6
    max_items: int = 4
    store_self_facts: bool = True
    store_user_facts: bool = True
    allow_general_from_auto: bool = False
    verbose: bool = True


class MemoryAutoUpdater:
    """Lightweight auto-memory extraction using the existing chat LLM.

    It asks the LLM to propose concise memory entries after each turn.
    Falls back to regex autocapture (via MemoryClient.try_autocapture) if LLM is unavailable.
    """

    def __init__(self, mem_client, llm, cfg: Optional[AutoMemoryConfig] = None):
        self.mem = mem_client
        self.llm = llm
        self.cfg = cfg or AutoMemoryConfig()

    def _build_prompt(self, user_text: str, assistant_text: str, working_summary: str) -> str:
        return (
            "You are a memory extraction assistant. Propose concise entries that will help future conversations.\n"
            "Return ONLY a JSON array of objects with fields: type, title, text, importance (0-10), tags (array).\n"
            "Use types among: user, semantic, general, goals. Avoid episodic unless truly important.\n"
            "- user: stable facts/preferences about the user (profile, likes, pronouns, goals).\n"
            "- semantic: durable facts about the world or the assistant.\n"
            "- general: project/doc knowledge that could be re-used.\n"
            "- goals: explicit goals the assistant should remember.\n"
            "Be brief, avoid redundancy, and set realistic importance. Max 4 items.\n\n"
            f"Working summary:\n{working_summary}\n\n"
            f"User said:\n{user_text}\n\n"
            f"Assistant replied:\n{assistant_text}\n"
        )

    def _parse_json_array(self, text: str) -> List[Dict[str, Any]]:
        # strip fences if present
        s = text.strip()
        if s.startswith("```"):
            s = s.strip("`")
        # find first [ ... ]
        start = s.find("[")
        end = s.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            arr = json.loads(s[start : end + 1])
            return arr if isinstance(arr, list) else []
        except Exception:
            return []

    def _map_type_to_label(self, typ: str, tags: List[str]) -> str:
        t = (typ or "").strip().lower()
        if t == "user":
            # prefer preferences if tag hints
            if any(tag.lower() in {"likes", "preferences", "style"} for tag in tags):
                return "preferences"
            return "profile"
        if t == "goals":
            return "goals"
        if t == "general":
            return "general"
        # default semantic facts
        return "facts"

    def _store_items(self, items: List[Dict[str, Any]]) -> int:
        stored = 0
        for it in items[: self.cfg.max_items]:
            try:
                typ = str(it.get("type", "") or "")
                title = str(it.get("title", "") or "").strip()
                text = str(it.get("text", "") or "").strip()
                imp = int(it.get("importance", 0) or 0)
                tags = it.get("tags") or []
                if not text:
                    continue
                if imp < int(self.cfg.importance_threshold):
                    continue
                label = self._map_type_to_label(typ, tags if isinstance(tags, list) else [])
                # Avoid overwriting persona via auto extraction
                if label == "persona":
                    continue
                # Skip general unless explicitly allowed
                if label == "general" and not self.cfg.allow_general_from_auto:
                    continue
                self.mem.write(label, f"{title + ': ' if title else ''}{text}")
                stored += 1
                if self.cfg.verbose:
                    print(f"[memory:auto] + {label}: {title + ': ' if title else ''}{text}")
            except Exception:
                continue
        return stored

    def process_turn(self, user_text: str, assistant_text: str, working_summary: str = "") -> Dict[str, Any]:
        """Extract memory candidates and persist them.

        Returns info dict with counts and errors if any.
        """
        info: Dict[str, Any] = {"enabled": bool(self.cfg.enable), "stored": 0}
        if not self.cfg.enable:
            return info
        # Fallback: regex autocapture for user-only facts
        try:
            self.mem.try_autocapture(user_text)
        except Exception:
            pass
        # If no llm or llm disabled, stop here
        if not self.llm or not getattr(self.llm, "enabled", True):
            return info
        try:
            prompt = self._build_prompt(user_text, assistant_text, working_summary)
            # Support both generate() and generate_from_messages()
            content = None
            if hasattr(self.llm, "generate"):
                content = self.llm.generate("", prompt)
            elif hasattr(self.llm, "generate_from_messages"):
                content = self.llm.generate_from_messages([
                    {"role": "system", "content": "Extract concise memory entries as JSON only."},
                    {"role": "user", "content": prompt},
                ])
            arr = self._parse_json_array(content or "")
            if not isinstance(arr, list):
                return info
            stored = self._store_items(arr)
            info["stored"] = stored
            return info
        except Exception as e:
            info["error"] = str(e)
            return info
