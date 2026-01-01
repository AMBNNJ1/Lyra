import os
import re
import json
from typing import Any, Dict, List, Optional, Tuple

from mem0 import MemoryClient as Mem0Client

_EMPTY_CONTEXT: Dict[str, Any] = {
    "persona": [],
    "user": [],
    "working": {"summary": "", "recent_turns": []},
    "long_term": [],
    "general": [],
}

MAX_MEMORY_LABEL_LENGTH = 64
MAX_MEMORY_VALUE_LENGTH = 4096


class MemoryClient:
    def __init__(self, provider: str | None = None, user_id: str | None = None) -> None:
        api_key = os.getenv("MEM0_API_KEY")
        if not api_key:
            raise ValueError("MEM0_API_KEY must be set for hosted Mem0")
        self.client = Mem0Client(api_key=api_key)
        self.provider = "mem0"
        self._debug = str(os.getenv("MEMORY_DEBUG", "0")).strip().lower() not in {"", "0", "false", "no"}
        self.user_id = self._sanitize_user(user_id or os.getenv("MEMORY_USER_ID", "default"))
        self.user_label = os.getenv("MEMORY_USER_LABEL", f"User is {self.user_id}.")
        self.persona_text: Optional[str] = os.getenv("MEMORY_PERSONA")

    def _dbg(self, msg: str) -> None:
        if self._debug:
            print(f"[memory:debug] {msg}")

    def _sanitize_user(self, text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text or "").strip("-").lower()
        return slug or "default"

    def _format_memory(self, item: Dict[str, Any] | str) -> Dict[str, Any]:
        # Handle string items from mem0 API (can return strings in some cases)
        if isinstance(item, str):
            label = self._infer_label(item)
            return {"id": None, "label": label, "value": item, "score": 1.0, "raw": item}
        content = str(item.get("content") or item.get("text") or item.get("value") or "")
        metadata = item.get("metadata") or {}
        label = metadata.get("label")
        if not label:
            label = self._infer_label(content)
        mem_id = item.get("id") or item.get("_id")
        score = item.get("score") or metadata.get("score") or 1.0
        return {"id": mem_id, "label": label, "value": content, "score": score, "raw": item}

    def _infer_label(self, content: str) -> str:
        match = re.match(r"^\s*\[(?P<label>[^\]]+)\]\s*", content)
        if match:
            return match.group("label").strip().lower()
        return "memory"

    def _ensure_base_user(self) -> None:
        if not self.user_label:
            return
        self.write("profile", self.user_label)

    def ensure_agent(self, persona: str, user_label: str, model: str | None = None, embedding: str | None = None) -> None:
        self.ensure_persona(persona)
        self.ensure_user(user_label)

    def ensure_persona(self, persona: str) -> None:
        persona = (persona or "").strip()
        if not persona:
            return
        self.persona_text = persona
        try:
            self.client.add([{"role": "system", "content": persona}], user_id=self.user_id, metadata={"label": "persona"})
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            self._dbg(f"ensure_persona failed: {exc}")

    def ensure_user(self, user_label: str) -> Optional[str]:
        user_label = (user_label or "User is default.").strip()
        self.user_label = user_label
        self.user_id = self._sanitize_user(user_label)
        try:
            self.client.add([{"role": "system", "content": user_label}], user_id=self.user_id, metadata={"label": "user"})
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            self._dbg(f"ensure_user failed: {exc}")
        else:
            self._ensure_base_user()
        return self.user_id

    def search(self, query: str) -> List[Dict[str, Any]]:
        try:
            filters = {"OR": [{"user_id": self.user_id}]}
            data = self.client.search(query or "", filters=filters, user_id=self.user_id, limit=24, version="v2")
            return [self._format_memory(item) for item in data]
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            self._dbg(f"search failed: {exc}")
            return []

    def find_items(self, query: str, labels: Optional[List[str]] = None, limit: int = 50, include_global: bool = False) -> List[Dict[str, Any]]:
        items = self.search(query)
        if labels:
            lowered = {lbl.lower() for lbl in labels}
            items = [it for it in items if it.get("label", "").lower() in lowered]
        return items[:limit]

    def write(self, label: str, value: str) -> None:
        label = (label or "memory").strip().lower()
        value = (value or "").strip()
        if not value:
            return
        # Validate and sanitize inputs
        if len(label) > MAX_MEMORY_LABEL_LENGTH:
            label = label[:MAX_MEMORY_LABEL_LENGTH]
        if len(value) > MAX_MEMORY_VALUE_LENGTH:
            value = value[:MAX_MEMORY_VALUE_LENGTH]
        # Only allow alphanumeric, underscore, hyphen for label
        label = re.sub(r"[^a-z0-9_\-]", "", label) or "memory"
        try:
            self.client.add([{"role": "assistant", "content": value}], user_id=self.user_id, metadata={"label": label})
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            self._dbg(f"write failed: {exc}")

    def log_interaction(self, user_text: str, assistant_text: str) -> None:
        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()
        if not user_text and not assistant_text:
            return
        messages = []
        if user_text:
            messages.append({"role": "user", "content": user_text})
        if assistant_text:
            messages.append({"role": "assistant", "content": assistant_text})
        try:
            self.client.add(messages, user_id=self.user_id)
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            self._dbg(f"log_interaction failed: {exc}")

    def retrieve_context(self, query: str, budget_tokens: int = 1024) -> Dict[str, Any]:
        results = self.search(query or "")
        persona: List[Dict[str, Any]] = []
        user: List[Dict[str, Any]] = []
        long_term: List[Dict[str, Any]] = []

        if self.persona_text:
            persona.append({"label": "persona", "value": self.persona_text})

        for item in results:
            label = (item.get("label") or "").lower()
            value = item.get("value", "")
            block = {"label": label or "memory", "value": value}
            if label == "persona":
                persona.append(block)
            elif label in {"user", "profile", "preferences", "facts", "goals"}:
                user.append(block)
            else:
                long_term.append(block)

        return {
            "persona": persona,
            "user": user,
            "working": {"summary": "", "recent_turns": []},
            "long_term": long_term,
            "general": []
        }

    def execute_tool(self, name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        t = (name or "").strip().lower()
        if t in {"memory_append", "memory_insert", "core_memory_append", "usermemory_append"}:
            label = (args.get("label") or "facts").strip().lower()
            value = str(args.get("value") or "").strip()
            if not value:
                return False, "value required"
            self.write(label, value)
            return True, "ok"
        if t == "memory_search":
            q = str(args.get("query") or args.get("q") or "").strip()
            labels = args.get("labels")
            if isinstance(labels, str):
                labels = [x.strip() for x in labels.split(",") if x.strip()]
            items = self.find_items(q, labels=labels, limit=int(args.get("k", 12) or 12))
            try:
                return True, json.dumps([{"label": it.get("label"), "text": it.get("value")} for it in items])
            except (TypeError, ValueError) as exc:
                self._dbg(f"JSON serialization failed in execute_tool: {exc}")
                return True, f"found:{len(items)}"
        return False, "unsupported"

    def log_tool_use(self, name: str, args: Dict[str, Any] | None, result: str | None, success: bool = True) -> None:
        if not success:
            self._dbg(f"tool failed: {name} -> {result}")

    def index_files(self, paths: Optional[List[str]] = None) -> int:
        return 0

    def export_json(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            filters = {"OR": [{"user_id": user_id or self.user_id}]}
            data = self.client.search("", filters=filters, version="v2")
            return {"user_id": user_id or self.user_id, "items": [self._format_memory(item) for item in data]}
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            self._dbg(f"export_json failed: {exc}")
            return {"user_id": user_id or self.user_id, "items": []}

    def forget_last_session(self, user_id: Optional[str] = None) -> int:
        return 0

    def forget_by_label(self, label: str, user_id: Optional[str] = None) -> int:
        return 0

    def wipe_user(self, user_id: Optional[str] = None) -> int:
        return 0

    def add_label_value(self, label: str, value: str, replace: bool = False) -> str:
        self.write(label, value)
        return ""

    def consolidate(self) -> Dict[str, int]:
        return {"merged": 0, "decayed": 0}

    def try_autocapture(self, user_text: str) -> List[Tuple[str, str]]:
        captures: List[Tuple[str, str]] = []
        if not user_text:
            return captures

        try:
            mfav = re.search(r"\b(?:my|our)\s+favorite\s+([a-z][a-z \-]{1,32})\s+(?:is|are)\s+([^.,!\n]+)", user_text, re.I)
            if mfav:
                cat = (mfav.group(1) or "").strip().lower()
                val = (mfav.group(2) or "").strip()
                if cat and val:
                    summary = f"favorite {cat}: {val}"
                    self.write("preferences", summary)
                    captures.append(("preferences", summary))
        except (re.error, ConnectionError, TimeoutError) as exc:
            self._dbg(f"Autocapture favorite pattern failed: {exc}")

        rules: List[Tuple[str, str, re.Pattern[str]]] = [
            ("profile", "name", re.compile(r"\b(my name is|call me)\s+([A-Z][A-Za-z\-']+)", re.I)),
            ("profile", "name", re.compile(r"\b(i\s*am|i'm)\s+([A-Z][A-Za-z\-']+)\b", re.I)),
            ("preferences", "likes", re.compile(r"\b(i like|i love|i enjoy|i prefer|favorite\s+\w+)\s+([^.,!\n]+)", re.I)),
            ("preferences", "likes", re.compile(r"\b(i (?:play|watch|code|program|develop))\s+([^.,!\n]+)", re.I)),
            ("preferences", "likes", re.compile(r"\bplaying\s+([^.,!\n]+)", re.I)),
            ("profile", "pronouns", re.compile(r"\b(my pronouns (are|'re))\s+([^.,!\n]+)", re.I)),
            ("profile", "location", re.compile(r"\b(i live in|i'm from|i am from)\s+([^.,!\n]+)", re.I)),
        ]
        for label, kind, pat in rules:
            m = pat.search(user_text)
            if not m:
                continue
            val = m.group(m.lastindex) if m.lastindex else m.group(0)
            try:
                sval = str(val).replace(" and ", "; ").replace(" also ", "; ")
            except (TypeError, AttributeError) as exc:
                self._dbg(f"Autocapture string conversion failed: {exc}")
                sval = val
            summary = f"{kind}: {sval}".strip()
            self.write(label, summary)
            captures.append((label, summary))
        return captures
