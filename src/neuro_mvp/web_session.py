from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional, Iterator
import re

from .memory import MemoryClient
from .emotion import EmotionEngine
from .sentiment import analyze_text_sentiment
from .memory_auto import MemoryAutoUpdater, AutoMemoryConfig
from .openai_compat import OpenAIChatLLM, ChatLLMConfig
from .qwen import QwenLLM, LLMConfig
from .agent_loop import Controller, build_tool_registry, Task, Goal
from .memory import MemoryClient  # re-import type for helper signature clarity


def _try_direct_memory_answer(mem: MemoryClient, question: str) -> Optional[str]:
    q = (question or "").strip().lower()
    if not q:
        return None
    m = re.search(r"what(?:'s| is)?\s+my\s+favorite\s+([a-z][a-z \-]{1,32})\??", q)
    if not m:
        return None
    cat = (m.group(1) or "").strip().strip(" .,")
    if not cat:
        return None
    try:
        items = mem.find_items(f"favorite {cat}", labels=["preferences", "profile", "facts"], limit=24)
    except Exception:
        items = []
    texts: List[str] = []
    for it in items or []:
        t = it.get("text")
        if t:
            texts.append(str(t))
    # Also scan generic blocks via search
    try:
        blocks = mem.search("") or []
        for b in blocks:
            if (b.get("label") in {"preferences", "profile", "facts"}) and b.get("value"):
                texts.append(str(b.get("value")))
    except Exception:
        pass
    rx = re.compile(rf"favorite\s+{re.escape(cat)}\s*(?:is|are|:)\s*([^\n\.;,]+)", re.I)
    for t in texts:
        m2 = rx.search(t)
        if m2:
            ans = (m2.group(1) or "").strip().strip(" .,")
            if ans:
                return f"You told me your favorite {cat} is {ans}."
    return None


class WebAgentSession:
    def __init__(self, cfg: Dict[str, Any], user_id: str = "default"):
        self.cfg = cfg
        self.mem = MemoryClient(provider=cfg.get("memory", {}).get("provider", "qdrant"), user_id=user_id)
        mem_cfg = cfg.get("memory", {})
        qdrant_cfg = mem_cfg.get("qdrant", {})
        persona = qdrant_cfg.get("persona") or mem_cfg.get("persona") or "Nova is friendly."
        user_label = qdrant_cfg.get("user_label") or mem_cfg.get("user_label") or f"User is {user_id}."
        self.mem.ensure_agent(persona=persona, user_label=user_label, model=None, embedding=None)
        try:
            # Simple startup note
            prov = self.mem.provider
            print(f"[web_session] Memory provider: {prov}")
        except Exception:
            pass

        # Affect
        self.ee = EmotionEngine()
        self.ee.add_goal("help_user", 1.0)

        # LLM
        llm_cfg_raw = cfg.get("models", {}).get("llm", {})
        provider = (llm_cfg_raw.get("provider", "openai_compat") or "openai_compat").lower()
        if provider in {"openai", "openai_compat", "lmstudio"}:
            self.llm = OpenAIChatLLM(ChatLLMConfig(
                base_url=llm_cfg_raw.get("base_url") or os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1"),
                model=llm_cfg_raw.get("id", "qwen2.5-3b-instruct"),
                max_new_tokens=int(llm_cfg_raw.get("max_new_tokens", 128)),
                temperature=float(llm_cfg_raw.get("temperature", 0.7)),
                api_key=os.getenv("OPENAI_API_KEY"),
            ))
        else:
            self.llm = QwenLLM(LLMConfig(
                model_id=llm_cfg_raw.get("id", "Qwen/Qwen3-8B"),
                max_new_tokens=int(llm_cfg_raw.get("max_new_tokens", 128)),
                temperature=float(llm_cfg_raw.get("temperature", 0.7)),
                thinking=bool(llm_cfg_raw.get("thinking", False)),
                device=cfg.get("models", {}).get("device", "auto"),
                cpu_safe=bool(cfg.get("models", {}).get("cpu_safe", True)),
            ))

        # Tools for JSON tool calls
        self.tools_controller = Controller(self.llm, self.mem, build_tool_registry(self.mem))

        # Auto memory updater
        auto_cfg = AutoMemoryConfig(
            enable=bool(cfg.get("memory", {}).get("auto", {}).get("enable", True)),
            importance_threshold=int(cfg.get("memory", {}).get("auto", {}).get("importance_threshold", 6)),
            max_items=int(cfg.get("memory", {}).get("auto", {}).get("max_items", 4)),
            store_self_facts=True,
            store_user_facts=True,
            allow_general_from_auto=bool(cfg.get("memory", {}).get("auto", {}).get("allow_general_from_auto", False)),
            verbose=bool(cfg.get("memory", {}).get("auto", {}).get("verbose", False)),
        )
        self.auto_mem = MemoryAutoUpdater(self.mem, llm=None, cfg=auto_cfg)

        # State
        self.history: List[Dict[str, str]] = []
        self.window_n = int(cfg.get("conversation", {}).get("window_messages", 10))
        self.require_input = bool(cfg.get("conversation", {}).get("require_input", True))
        self.autodrive_timeout_s = float(cfg.get("conversation", {}).get("autodrive_input_timeout_sec", 2))
        self.continuous_enabled = False
        self._lock = threading.Lock()
        self._stop = False
        self._thread: Optional[threading.Thread] = None

    def start_continuous(self) -> None:
        with self._lock:
            self.continuous_enabled = True
            if self._thread is None or not self._thread.is_alive():
                self._stop = False
                self._thread = threading.Thread(target=self._continuous_loop, daemon=True)
                self._thread.start()

    def stop_continuous(self) -> None:
        with self._lock:
            self.continuous_enabled = False
            self._stop = True

    def truncated_history(self) -> List[Dict[str, str]]:
        return self.history[-self.window_n:] if len(self.history) > self.window_n else list(self.history)

    def _build_system_seed(self, last_user: Optional[str]) -> str:
        try:
            rel = self.mem.search("goals")
        except Exception:
            rel = []
        persona_blocks = [r for r in rel if r.get('label') in {"persona", "user", "profile", "facts", "preferences"}]
        persona_text = "\n".join([f"- {b.get('value','')}" for b in persona_blocks if b.get('value')])
        goals_lines = [f"- {r.get('value','')}" for r in rel if r.get('label') == 'goals' and r.get('value')]
        goals_text = "\n".join(goals_lines)
        try:
            ctx = self.mem.retrieve_context(last_user or "", budget_tokens=int(os.getenv("MEMORY_BUDGET_TOKENS", "1024")))
        except Exception:
            ctx = {"working": {"summary": ""}, "long_term": []}
        working_text = (ctx.get("working", {}) or {}).get("summary") or ""
        lt_lines = [f"- {it.get('value','')[:180]}" for it in (ctx.get("long_term") or [])[:6] if it.get('value')]
        long_term_text = "\n".join(lt_lines)
        affect_line = self.ee.to_prompt()
        base_system = (
            "You are Nova, a friendly companion. Keep context coherent and grounded.\n"
            "Anchor your reply to the user's latest message; do not change topics.\n"
            "You HAVE long-term memory and can recall user facts. Use the Long-term memory bullets below when relevant.\n"
            "Never claim you have no memory. If nothing relevant is found, say you couldn't find it yet and ask briefly to share it so you can remember.\n"
            "Ask at most one short question when helpful. Tone: concise, warm; avoid filler.\n"
        )
        seed = base_system + \
               ("\n" + affect_line if affect_line else "") + \
               (f"\nPersona and facts:\n{persona_text}" if persona_text else "") + \
               (f"\nCurrent goals:\n{goals_text}" if goals_text else "") + \
               (f"\nWorking summary:\n{working_text}" if working_text else "") + \
               (f"\nLong-term memory:\n{long_term_text}" if long_term_text else "") + \
               "\n\nIf the user's message requires up-to-date information, current events, or facts not in memory, use the 'search' tool to query the web before responding. Format tool calls as JSON: {\"thought\": \"reason\", \"action\": {\"name\": \"search\", \"args\": {\"query\": \"your query\"}}}."
        return seed

    def chat(self, user_text: str) -> Dict[str, Any]:
        user_text = (user_text or "").strip()
        if user_text:
            self.history.append({"role": "user", "content": user_text})
            try:
                self.ee.appraise_from_text(user_text)
            except Exception:
                pass
        # Fast path: direct memory Q&A for profile/preferences (e.g., "What is my favorite food?")
        try:
            direct = _try_direct_memory_answer(self.mem, user_text)
        except Exception:
            direct = None
        if direct:
            assistant = direct
            self.history.append({"role": "assistant", "content": assistant})
            # Persist and auto memory same as below
            try:
                if user_text:
                    self.mem.log_interaction(user_text, assistant)
                    _ = self.mem.try_autocapture(user_text)
                ctx_pack = self.mem.retrieve_context(user_text or "", budget_tokens=int(os.getenv("MEMORY_BUDGET_TOKENS", "1024")))
                working_summary = (ctx_pack.get("working", {}) or {}).get("summary") or ""
                self.auto_mem.llm = self.llm
                self.auto_mem.process_turn(user_text or "", assistant, working_summary)
            except Exception:
                pass
            return {"reply": assistant, "messages": self.truncated_history()}
    
        # Use Controller for tool-aware response
        goal = self.tools_controller.select_goal()  # Use a general goal for user response
        task = self.tools_controller.ensure_tasks(goal)[0] if self.tools_controller.ensure_tasks(goal) else None
        if not task:
            task = Task(id="t_general", text="Respond to the user message, using tools if needed for information.", goal_id=goal.id)
        memories = self.tools_controller.retrieve_memories(goal, task)
        prompt = self.tools_controller.build_prompt(goal, task, memories)
        llm_out = self.tools_controller.run_llm(prompt)
        action = self.tools_controller.choose_action(prompt, task, llm_out)
        if action:
            obs = self.tools_controller.dispatch(action)
            tool_ctx = f"Tool result: {obs.text}"
            # Re-run LLM with tool observation
            prompt2 = prompt + f"\n\nUser message: {user_text}\n{tool_ctx}\nNow generate the final response."
            llm_out2 = self.tools_controller.run_llm(prompt2)
            assistant = str(llm_out2)
        else:
            assistant = str(llm_out)
    
        self.history.append({"role": "assistant", "content": assistant})
    
        # Sentiment, auto memory
        try:
            ts = analyze_text_sentiment(assistant)
            _ = ts.label
        except Exception:
            pass
        # Persist turn and update memories similar to terminal app
        try:
            if user_text:
                self.mem.log_interaction(user_text, assistant)
                _ = self.mem.try_autocapture(user_text)
            ctx_pack = self.mem.retrieve_context(user_text or "", budget_tokens=int(os.getenv("MEMORY_BUDGET_TOKENS", "1024")))
            working_summary = (ctx_pack.get("working", {}) or {}).get("summary") or ""
            self.auto_mem.llm = self.llm
            self.auto_mem.process_turn(user_text or "", assistant, working_summary)
        except Exception:
            pass
    
        return {"reply": assistant, "messages": self.truncated_history()}

    def stream_chat(self, user_text: str) -> Iterator[str]:
        """Yield assistant text deltas for streaming web UI.
    
        Falls back to a single non-streaming completion when the underlying LLM
        does not support streaming.
        """
        user_text = (user_text or "").strip()
        if user_text:
            self.history.append({"role": "user", "content": user_text})
            try:
                self.ee.appraise_from_text(user_text)
            except Exception:
                pass
    
        # Fast path: direct memory Q&A for profile/preferences
        try:
            direct = _try_direct_memory_answer(self.mem, user_text)
        except Exception:
            direct = None
        if direct:
            assistant = direct
            self.history.append({"role": "assistant", "content": assistant})
            try:
                if user_text:
                    self.mem.log_interaction(user_text, assistant)
                    _ = self.mem.try_autocapture(user_text)
                ctx_pack = self.mem.retrieve_context(user_text or "", budget_tokens=int(os.getenv("MEMORY_BUDGET_TOKENS", "1024")))
                working_summary = (ctx_pack.get("working", {}) or {}).get("summary") or ""
                self.auto_mem.llm = self.llm
                self.auto_mem.process_turn(user_text or "", assistant, working_summary)
            except Exception:
                pass
            yield assistant
            return
    
        # Use Controller for tool-aware response (resolve tools first, then stream final)
        goal = self.tools_controller.select_goal()  # Use a general goal for user response
        task = self.tools_controller.ensure_tasks(goal)[0] if self.tools_controller.ensure_tasks(goal) else None
        if not task:
            task = Task(id="t_general", text="Respond to the user message, using tools if needed for information.", goal_id=goal.id)
        memories = self.tools_controller.retrieve_memories(goal, task)
        prompt = self.tools_controller.build_prompt(goal, task, memories)
        llm_out = self.tools_controller.run_llm(prompt)
        action = self.tools_controller.choose_action(prompt, task, llm_out)
        tool_ctx = ""
        if action:
            obs = self.tools_controller.dispatch(action)
            tool_ctx = f"Tool result: {obs.text}"
            # Re-run LLM with tool observation for final response
            prompt2 = prompt + f"\n\nUser message: {user_text}\n{tool_ctx}\nNow generate the final response."
            llm_out2 = self.tools_controller.run_llm(prompt2)
            assistant = str(llm_out2)
        else:
            assistant = str(llm_out)
    
        # Stream the final assistant response
        if isinstance(self.llm, OpenAIChatLLM):
            # Reconstruct messages for streaming the final response
            messages_final = [{"role": "system", "content": self._build_system_seed(user_text)}] + self.truncated_history() + [{"role": "user", "content": tool_ctx if tool_ctx else user_text}]
            try:
                for piece in self.llm.stream_from_messages(messages_final):
                    if isinstance(piece, str) and piece:
                        yield piece
            except Exception:
                yield assistant
        else:
            yield assistant
    
        self.history.append({"role": "assistant", "content": assistant})
    
        # Post-processing: sentiment and memory updates
        try:
            ts = analyze_text_sentiment(assistant)
            _ = ts.label
        except Exception:
            pass
        try:
            if user_text:
                self.mem.log_interaction(user_text, assistant)
                _ = self.mem.try_autocapture(user_text)
            ctx_pack = self.mem.retrieve_context(user_text or "", budget_tokens=int(os.getenv("MEMORY_BUDGET_TOKENS", "1024")))
            working_summary = (ctx_pack.get("working", {}) or {}).get("summary") or ""
            self.auto_mem.llm = self.llm
            self.auto_mem.process_turn(user_text or "", assistant, working_summary)
        except Exception:
            pass
    
        # Nothing else to yield; the SSE route will append [DONE]
        return

    def _continuous_loop(self) -> None:
        last_len = len(self.history)
        # Wait a short grace period so server is ready
        time.sleep(0.2)
        while True:
            with self._lock:
                if self._stop:
                    return
                cont = self.continuous_enabled
            if not cont:
                time.sleep(0.2)
                continue
            try:
                # If no new user message in timeout, self-continue
                start_len = len(self.history)
                waited = 0.0
                step = 0.2
                while waited < max(self.autodrive_timeout_s, 0.5):
                    time.sleep(step)
                    waited += step
                    if len(self.history) > start_len and self.history[-1]["role"] == "user":
                        break
                # If still no user, self-continue by sending empty user signal
                if len(self.history) == start_len:
                    self.chat("")
                last_len = len(self.history)
            except Exception:
                time.sleep(0.5)
                continue


