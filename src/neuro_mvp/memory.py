import os
import re
import json
from typing import Any, Dict, List, Optional, Tuple

import requests

_EMPTY_CONTEXT: Dict[str, Any] = {
    "persona": [],
    "user": [],
    "working": {"summary": "", "recent_turns": []},
    "long_term": [],
    "general": [],
}


class MemoryClient:
    def __init__(self, provider: str | None = None) -> None:
        self.base_url = os.getenv("MEM0_BASE_URL", "http://127.0.0.1:4040").rstrip("/")
        self.session = requests.Session()
        self._debug = str(os.getenv("MEMORY_DEBUG", "0")).strip().lower() not in {"", "0", "false", "no"}
        self.user_id = self._sanitize_user(os.getenv("MEMORY_USER_ID", "default"))
        self.user_label = os.getenv("MEMORY_USER_LABEL", "User is default.")
        self.persona_text: Optional[str] = os.getenv("MEMORY_PERSONA")

    def _dbg(self, msg: str) -> None:
        if self._debug:
            print(f"[memory:debug] {msg}")

    def _sanitize_user(self, text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text or "").strip("-").lower()
        return slug or "default"

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self.session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}

    def _format_memory(self, item: Dict[str, Any]) -> Dict[str, Any]:
        content = str(item.get("content") or item.get("text") or item.get("value") or "")
        metadata = item.get("metadata") or {}
        label = metadata.get("label")
        if not label:
            label = self._infer_label(content)
        mem_id = item.get("id") or item.get("_id")
        score = item.get("score") or metadata.get("score")
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
            self._post("/add", {
                "userId": self.user_id,
                "messages": [{"role": "system", "content": f"[persona] {persona}"}]
            })
        except Exception as exc:  # noqa: BLE001
            self._dbg(f"ensure_persona failed: {exc}")

    def ensure_user(self, user_label: str) -> Optional[str]:
        user_label = (user_label or "User is default.").strip()
        self.user_label = user_label
        self.user_id = self._sanitize_user(user_label)
        try:
            self._post("/add", {
                "userId": self.user_id,
                "messages": [{"role": "system", "content": f"[user] {user_label}"}]
            })
        except Exception as exc:  # noqa: BLE001
            self._dbg(f"ensure_user failed: {exc}")
        else:
            self._ensure_base_user()
        return self.user_id

    def search(self, query: str) -> List[Dict[str, Any]]:
        try:
            data = self._post("/search", {"userId": self.user_id, "query": query or "", "limit": 24})
            return [self._format_memory(item) for item in data.get("results", [])]
        except Exception as exc:  # noqa: BLE001
            self._dbg(f"search failed: {exc}")
            return []

    def find_items(self, query: str, labels: Optional[List[str]] = None, limit: int = 50, include_global: bool = False) -> List[Dict[str, Any]]:
        items = self.search(query)
        if labels:
            lowered = {lbl.lower() for lbl in labels}
            items = [it for it in items if it.get("label", "").lower() in lowered]
        return items[: limit]

    def write(self, label: str, value: str) -> None:
        label = (label or "memory").strip().lower()
        value = (value or "").strip()
        if not value:
            return
        try:
            self._post("/add", {
                "userId": self.user_id,
                "messages": [{"role": "assistant", "content": f"[{label}] {value}"}]
            })
        except Exception as exc:  # noqa: BLE001
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
            self._post("/add", {"userId": self.user_id, "messages": messages})
        except Exception as exc:  # noqa: BLE001
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
                return True, json.dumps([{ "label": it.get("label"), "text": it.get("value") } for it in items])
            except Exception:
                return True, f"found:{len(items)}"
        return False, "unsupported"

    def log_tool_use(self, name: str, args: Dict[str, Any] | None, result: str | None, success: bool = True) -> None:
        if not success:
            self._dbg(f"tool failed: {name} -> {result}")

    def index_files(self, paths: Optional[List[str]] = None) -> int:
        return 0

    def export_json(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            data = self._post("/history", {"userId": user_id or self.user_id, "limit": 500})
            return {"user_id": user_id or self.user_id, "items": data.get("items", [])}
        except Exception as exc:  # noqa: BLE001
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
                    ok, _ = self.execute_tool("memory_append", {"label": "preferences", "value": summary})
                    if ok:
                        captures.append(("preferences", summary))
        except Exception:
            pass

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
            except Exception:
                sval = val
            summary = f"{kind}: {sval}".strip()
            ok, _ = self.execute_tool("memory_append" if label != "profile" else "usermemory_append", {"label": label, "value": summary})
            if ok:
                captures.append((label, summary))
        return captures
