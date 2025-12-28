from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import json
import re
import time

from .memory import MemoryClient
from .web_search_tool import web_search_tool
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# URL allowlist for browse() - only public HTTP(S) URLs allowed
BROWSE_ALLOWED_SCHEMES = {"http", "https"}
BROWSE_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
    "metadata.google.internal",
    "169.254.169.254",  # AWS/GCP metadata endpoint
}
BROWSE_BLOCKED_HOST_PATTERNS = [
    r"^10\.",            # 10.0.0.0/8
    r"^172\.(1[6-9]|2[0-9]|3[0-1])\.",  # 172.16.0.0/12
    r"^192\.168\.",      # 192.168.0.0/16
    r"\.local$",         # mDNS
    r"\.internal$",      # internal domains
]


def _is_url_allowed(url: str) -> tuple[bool, str]:
    """Validate URL against SSRF blocklist. Returns (allowed, reason)."""
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False, "invalid URL format"

    if parsed.scheme.lower() not in BROWSE_ALLOWED_SCHEMES:
        return False, f"scheme '{parsed.scheme}' not allowed"

    host = (parsed.hostname or "").lower()
    if not host:
        return False, "missing hostname"

    if host in BROWSE_BLOCKED_HOSTS:
        return False, f"host '{host}' is blocked"

    for pattern in BROWSE_BLOCKED_HOST_PATTERNS:
        if re.search(pattern, host, re.I):
            return False, f"host '{host}' matches blocked pattern"

    # Block URLs with credentials
    if parsed.username or parsed.password:
        return False, "URLs with credentials not allowed"

    return True, ""


@dataclass
class Goal:
    id: str
    text: str
    serves: List[str] = field(default_factory=list)
    created_ts: float = field(default_factory=time.time)


@dataclass
class Task:
    id: str
    text: str
    goal_id: str
    status: str = "pending"  # pending | done | failed
    criteria: Optional[Dict[str, Any]] = None


@dataclass
class Action:
    name: str
    args: Dict[str, Any]


@dataclass
class Observation:
    text: str
    ok: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Critique:
    score: float
    next_step: str  # proceed | revise | retry | stop
    note: str = ""


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, tuple[Callable[..., Any], str]] = {}

    def register(self, name: str, fn: Callable[..., Any], desc: str = "") -> None:
        self._tools[name] = (fn, desc)

    def call(self, name: str, **kwargs: Any) -> Observation:
        fn = self._tools.get(name, (None, ""))[0]
        if not fn:
            return Observation(text=f"unknown tool: {name}", ok=False)
        try:
            res = fn(**kwargs)
            if isinstance(res, (dict, list)):
                return Observation(text=json.dumps(res)[:4000], ok=True, meta={"raw": res})
            return Observation(text=str(res)[:4000], ok=True)
        except (TypeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
            logger.debug("Tool %s execution failed: %s", name, e)
            return Observation(text=f"error: {e}", ok=False)


def build_tool_registry(mem: MemoryClient) -> ToolRegistry:
    import httpx

    reg = ToolRegistry()

    def search(query: str, k: int = 6) -> Dict[str, Any]:
        return web_search_tool(query, k=k)

    def browse(url: str, max_chars: int = 4000) -> str:
        allowed, reason = _is_url_allowed(url)
        if not allowed:
            return f"URL blocked: {reason}"
        r = httpx.get(url, timeout=15, headers={"User-Agent": "Nova/1.0"}, follow_redirects=False)
        # Check for redirects to blocked URLs
        if r.is_redirect:
            redirect_url = r.headers.get("location", "")
            redirect_allowed, redirect_reason = _is_url_allowed(redirect_url)
            if not redirect_allowed:
                return f"Redirect URL blocked: {redirect_reason}"
            r = httpx.get(redirect_url, timeout=15, headers={"User-Agent": "Nova/1.0"}, follow_redirects=False)
        r.raise_for_status()
        txt = r.text
        try:
            import trafilatura  # type: ignore
            body = trafilatura.extract(txt, include_comments=False, favor_recall=True) or ""
        except (ImportError, ValueError, TypeError) as exc:
            logger.debug("Trafilatura extraction failed, using regex fallback: %s", exc)
            body = re.sub(r"<script[\s\S]*?</script>", " ", txt, flags=re.I)
            body = re.sub(r"<style[\s\S]*?</style>", " ", body, flags=re.I)
            body = re.sub(r"<[^>]+>", " ", body)
        return (body or "")[: int(max_chars or 4000)]

    def retrieve_memory(query: str, top_k: int = 8) -> Dict[str, Any]:
        items = mem.find_items(query, limit=int(top_k or 8))
        return {"items": items}

    def store_memory(text: str, label: str = "facts") -> str:
        return mem.add_label_value(label, text, replace=False)

    reg.register("search", search, "Web search")
    reg.register("browse", browse, "Fetch and extract page content")
    reg.register("retrieve_memory", retrieve_memory, "Query long-term memory store")
    reg.register("store_memory", store_memory, "Append text to memory under a label")
    return reg


class Controller:
    def __init__(self, llm: Any, mem: MemoryClient, tools: ToolRegistry):
        self.llm = llm
        self.mem = mem
        self.tools = tools
        self.medium_goals: List[Goal] = []
        self.task_queue: List[Task] = []
        self.working_log: List[str] = []

    # --- Planning / selection ---
    def select_goal(self) -> Goal:
        if self.medium_goals:
            return self.medium_goals[0]
        g = Goal(id="g1", text="Learn a small new fact to share with the user.", serves=["learn_world", "entertain_user"])
        self.medium_goals.append(g)
        return g

    def ensure_tasks(self, goal: Goal) -> List[Task]:
        existing = [t for t in self.task_queue if t.goal_id == goal.id and t.status == "pending"]
        if existing:
            return existing
        plan = [
            Task(id="t1", text="compose_opening: ask a short engaging question to the user", goal_id=goal.id, criteria={"len_max": 40}),
            Task(id="t2", text="search: latest developments in AI art", goal_id=goal.id, criteria={"have_links": 1}),
            Task(id="t3", text="summarize: top result to <400 words", goal_id=goal.id, criteria={"len_max": 400}),
            Task(id="t4", text="store_memory: key points with tags", goal_id=goal.id),
            Task(id="t5", text="compose_fun_fact: 2 sentences", goal_id=goal.id, criteria={"len_max": 60}),
        ]
        self.task_queue.extend(plan)
        return plan

    def next_task(self, tasks: List[Task]) -> Task:
        for t in tasks:
            if t.status == "pending":
                return t
        raise RuntimeError("no pending tasks")

    # --- Memory retrieval / prompt building ---
    def retrieve_memories(self, goal: Goal, task: Task) -> List[Dict[str, Any]]:
        try:
            ctx = self.mem.retrieve_context(goal.text, budget_tokens=512)
        except (ConnectionError, TimeoutError, ValueError) as exc:
            logger.debug("Memory retrieval for goal failed: %s", exc)
            return []
        return (ctx.get("long_term") or [])[:6]

    def build_prompt(self, goal: Goal, task: Task, memories: List[Dict[str, Any]]) -> str:
        mem_lines: List[str] = []
        for m in memories:
            val = (m.get('value') or m.get('text') or '').strip()
            if val:
                mem_lines.append(f"- {val}")
        tools_block = (
            "Available tools (use only when necessary):\n"
            "- search(query, k=6) — web search results list\n"
            "- browse(url, max_chars=4000) — fetch and extract page text\n"
            "- retrieve_memory(query, top_k=8) — query long-term memory\n"
            "- store_memory(text, label='facts') — append memory entry\n"
        )
        schema_block = (
            "Default to a short conversational message (plain text).\n"
            "Only when an external tool is essential, respond with ONLY JSON: {\"thought\": \"...\", \"action\": {\"name\": \"...\", \"args\": {}}}.\n"
        )
        return (
            "You are Lyra. Prefer brief, engaging interaction; use tools sparingly.\n"
            + tools_block
            + schema_block
            + f"Goal: {goal.text}\nTask: {task.text}\nRelevant memory:\n" + "\n".join(mem_lines)
        )

    # --- LLM run and action parsing ---
    def run_llm(self, prompt: str) -> str | Dict[str, Any]:
        system = "You are a helpful autonomous assistant."
        if hasattr(self.llm, "generate"):
            return self.llm.generate(system, prompt)
        if hasattr(self.llm, "generate_from_messages"):
            return self.llm.generate_from_messages([
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ])
        return ""

    def parse_action(self, out: str | Dict[str, Any]) -> Optional[Action]:
        if isinstance(out, dict) and out.get("action"):
            a = out["action"]
            return Action(a.get("name", ""), a.get("args", {}))
        # Try JSON
        try:
            js = json.loads(str(out))
            if isinstance(js, dict) and js.get("action"):
                a = js["action"]
                return Action(a.get("name", ""), a.get("args", {}))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.debug("JSON action parsing failed: %s", exc)
        # ReAct-style
        m = re.search(r"Action:\s*([A-Z_]+)\s*Action Input:\s*(.+)", str(out), re.I | re.S)
        if m:
            return Action(m.group(1).strip().lower(), {"input": m.group(2).strip()})
        return None

    def infer_action_from_task(self, task: Task) -> Optional[Action]:
        t = (task.text or "").strip().lower()
        if t.startswith("search:"):
            q = t.split(":", 1)[1].strip()
            return Action("search", {"query": q, "k": 6})
        if t.startswith("browse:"):
            url = t.split(":", 1)[1].strip()
            return Action("browse", {"url": url})
        if t.startswith("store_memory:"):
            val = t.split(":", 1)[1].strip()
            return Action("store_memory", {"text": val, "label": "facts"})
        if t.startswith("retrieve_memory:"):
            q = t.split(":", 1)[1].strip()
            return Action("retrieve_memory", {"query": q, "top_k": 8})
        return None

    def choose_action(self, prompt: str, task: Task, llm_output: str | Dict[str, Any]) -> Optional[Action]:
        # Prefer no tool: if output isn't a valid action, treat as conversational
        a = self.parse_action(llm_output)
        if a:
            return a
        # If the task explicitly encodes a tool, infer it; otherwise, no action
        return self.infer_action_from_task(task)

    # --- Dispatch and bookkeeping ---
    def dispatch(self, action: Action) -> Observation:
        return self.tools.call(action.name, **(action.args or {}))

    def observe_thought(self, out: str | Dict[str, Any]) -> Observation:
        return Observation(text=str(out)[:1000], ok=True)

    def update_working_memory(self, task: Task, obs: Observation) -> None:
        self.working_log.append(f"{task.id}:{task.text} -> {obs.ok}")

    def maybe_store_long_term(self, task: Task, obs: Observation) -> None:
        try:
            if task.text.startswith("store_memory"):
                return
            if obs.ok and len((obs.text or "")) > 80:
                self.mem.add_label_value("facts", obs.text[:512], replace=False)
        except (ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            logger.debug("Failed to store long-term memory: %s", exc)

    def criticize(self, goal: Goal, task: Task, obs: Observation) -> Critique:
        ok = obs.ok
        return Critique(score=1.0 if ok else 0.2, next_step="proceed" if ok else "revise", note=obs.text[:140])

    def adjust_plan(self, tasks: List[Task], critique: Critique) -> None:
        # Placeholder for richer plan adaptation
        return

    def should_terminate(self, goal: Goal, tasks: List[Task], critique: Critique) -> bool:
        return all(t.status != "pending" for t in tasks)


