import argparse
import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

from src.neuro_mvp.agent_loop import Controller, build_tool_registry
from src.neuro_mvp.emotion import EmotionEngine
from src.neuro_mvp.memory import MemoryClient
from src.neuro_mvp.memory_auto import AutoMemoryConfig, MemoryAutoUpdater
from src.neuro_mvp.openai_compat import ChatLLMConfig, OpenAIChatLLM, OpenAIChatVLM
from src.neuro_mvp.qwen import LLMConfig, QwenLLM, QwenVLM, VLMConfig
from src.neuro_mvp.sentiment import analyze_text_sentiment
from src.neuro_mvp.tts_kokoro import KokoroTTS
from src.neuro_mvp.web_search_tool import pack_for_context, search_and_extract


def _ensure_utf8_stdio() -> None:
    """Best-effort: make stdout/stderr UTF-8 so emojis render on Windows."""

    try:
        if hasattr(__import__("sys").stdout, "reconfigure"):
            __import__("sys").stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(__import__("sys").stderr, "reconfigure"):
            __import__("sys").stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


load_dotenv()
_ensure_utf8_stdio()


def try_direct_memory_answer(mem: MemoryClient, question: str) -> Optional[str]:
    """Lightweight heuristics for ?what's my favorite X?"""

    import re

    q = (question or "").strip()
    if not q:
        return None
    match = re.search(r"what(?:'s| is)?\s+my\s+favorite\s+([a-z][a-z \-]{1,32})\??", q.lower())
    if not match:
        return None
    category = (match.group(1) or "").strip().strip(" .,!")
    if not category:
        return None

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

    rx_explicit = re.compile(rf"favorite\s+{re.escape(category)}\s*(?:is|are|:)\s*([^\n\.;,]+)", re.I)
    for line in candidate_lines:
        matches = list(rx_explicit.finditer(line))
        if not matches:
            continue
        value = (matches[-1].group(1) or "").strip()
        value = re.sub(rf"^(?:user['’]s|my|the user['’]s)\s+favorite\s+{re.escape(category)}\s*(?:is|are|:)\s*",
                        "", value, flags=re.I).strip(" .,!")
        if value and not any(value.lower().startswith(prefix) for prefix in ("what", "who", "where", "when", "why", "how")):
            return f"You told me your favorite {category} is {value}."

    rx_like = re.compile(rf"\b(?:i\s+)?(?:like|love|enjoy|prefer)\s+([^\n\.;,]+)", re.I)
    likes: List[str] = []
    for text in texts:
        if category in text.lower():
            like_match = rx_like.search(text)
            if like_match:
                candidate = (like_match.group(1) or "").strip().strip(" .,!")
                if candidate and candidate.lower() != category:
                    likes.append(candidate)
    unique_likes: List[str] = []
    seen: set[str] = set()
    for value in likes:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_likes.append(value)
    if unique_likes:
        if len(unique_likes) == 1:
            return f"You’ve said you like {unique_likes[0]}. Is that your favorite {category}?"
        return f"You’ve mentioned liking {', '.join(unique_likes[:3])}. Do you have one favorite {category}?"
    return None


def load_config() -> Dict[str, Any]:
    cfg_path = Path("config.yaml")
    cfg: Dict[str, Any] = {}
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("tts", {})
    cfg.setdefault("memory", {})
    cfg["memory"]["provider"] = os.getenv("MEMORY_PROVIDER", cfg["memory"].get("provider", "qdrant"))
    return cfg


def safe_print(text: str) -> None:
    try:
        print(text)
    except Exception:
        try:
            __import__("sys").stdout.buffer.write((text + "\n").encode("utf-8", "replace"))
        except Exception:
            pass


async def synthesize(cfg: Dict[str, Any], text: str) -> Optional[Path]:
    tts_cfg = cfg.get("tts", {})
    if not bool(tts_cfg.get("enable", False)):
        return None
    kokoro_cfg = tts_cfg.get("kokoro", {})
    voice = os.getenv("KOKORO_VOICE", kokoro_cfg.get("voice", "af_heart"))
    lang = os.getenv("KOKORO_LANG", kokoro_cfg.get("lang", "a"))
    out_path = Path(kokoro_cfg.get("out_path", tts_cfg.get("out_path", "response.wav")))
    tts = KokoroTTS(lang_code=lang, voice=voice)
    tts.synthesize_to_wav(text, str(out_path))
    return out_path


class AgentRuntime:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        mem_cfg = cfg.get("memory", {})
        provider = (mem_cfg.get("provider") or "qdrant").lower()
        self.mem = MemoryClient(provider=provider)

        qdrant_cfg = mem_cfg.get("qdrant", {})
        persona = qdrant_cfg.get("persona") or mem_cfg.get("persona") or "Nova is friendly."
        user_label = qdrant_cfg.get("user_label") or mem_cfg.get("user_label") or "User is Sam."
        self.mem.ensure_agent(persona=persona, user_label=user_label, model=None, embedding=None)

        self.ee = EmotionEngine()
        self.ee.add_goal("help_user", 1.0)

        models_cfg = cfg.get("models", {})
        llm_cfg_raw = models_cfg.get("llm", {})
        device = models_cfg.get("device", "auto")
        cpu_safe = bool(models_cfg.get("cpu_safe", True))
        provider_name = (llm_cfg_raw.get("provider") or "transformers").lower()
        if provider_name in {"openai", "openai_compat", "lmstudio"}:
            chat_cfg = ChatLLMConfig(
                base_url=llm_cfg_raw.get("base_url") or os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1"),
                model=llm_cfg_raw.get("id", "qwen2.5-3b-instruct"),
                max_new_tokens=int(llm_cfg_raw.get("max_new_tokens", 128)),
                temperature=float(llm_cfg_raw.get("temperature", 0.7)),
                api_key=os.getenv("OPENAI_API_KEY"),
            )
            self.llm = OpenAIChatLLM(chat_cfg)
        else:
            qwen_cfg = LLMConfig(
                model_id=llm_cfg_raw.get("id", "Qwen/Qwen3-8B"),
                max_new_tokens=int(llm_cfg_raw.get("max_new_tokens", 128)),
                temperature=float(llm_cfg_raw.get("temperature", 0.7)),
                thinking=bool(llm_cfg_raw.get("thinking", False)),
                device=device,
                cpu_safe=cpu_safe,
            )
            self.llm = QwenLLM(qwen_cfg)

        vlm_cfg_raw = models_cfg.get("vlm", {})
        self.vlm = None
        if vlm_cfg_raw.get("enable", False):
            provider_vlm = (vlm_cfg_raw.get("provider") or "transformers").lower()
            if provider_vlm in {"openai", "openai_compat", "lmstudio"}:
                self.vlm = OpenAIChatVLM(ChatVLMConfig(
                    base_url=vlm_cfg_raw.get("base_url") or os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1"),
                    model=vlm_cfg_raw.get("id", "qwen2.5-3b-instruct"),
                    max_new_tokens=int(vlm_cfg_raw.get("max_new_tokens", 128)),
                    temperature=float(vlm_cfg_raw.get("temperature", 0.7)),
                    api_key=os.getenv("OPENAI_API_KEY"),
                ))
            else:
                self.vlm = QwenVLM(VLMConfig(
                    model_id=vlm_cfg_raw.get("id", "Qwen/Qwen2.5-VL-7B-Instruct"),
                    max_new_tokens=int(vlm_cfg_raw.get("max_new_tokens", 128)),
                    device=device,
                    cpu_safe=cpu_safe,
                    local_files_only=bool(vlm_cfg_raw.get("local_only", False)),
                    revision=vlm_cfg_raw.get("revision"),
                ))

        auto_cfg = AutoMemoryConfig(
            enable=bool(mem_cfg.get("auto", {}).get("enable", True)),
            importance_threshold=int(mem_cfg.get("auto", {}).get("importance_threshold", 6)),
            max_items=int(mem_cfg.get("auto", {}).get("max_items", 4)),
            store_self_facts=True,
            store_user_facts=True,
            allow_general_from_auto=bool(mem_cfg.get("auto", {}).get("allow_general_from_auto", False)),
            verbose=bool(mem_cfg.get("auto", {}).get("verbose", False)),
        )
        self.auto_mem = MemoryAutoUpdater(self.mem, llm=None, cfg=auto_cfg)

        try:
            self.tools = Controller(self.llm, self.mem, build_tool_registry(self.mem))
        except Exception:
            self.tools = None

        self.history: List[Dict[str, str]] = []
        self.turn_count = 0

    def truncated_history(self) -> List[Dict[str, str]]:
        window_n = int(self.cfg.get("conversation", {}).get("window_messages", 10))
        hist = self.history
        return hist[-window_n:] if len(hist) > window_n else list(hist)


def _gather_prompt_context(run: AgentRuntime, last_user: Optional[str]) -> Dict[str, Any]:
    mem = run.mem
    try:
        rel = mem.search("goals")
    except Exception:
        rel = []
    persona_blocks = [r for r in rel if r.get("label") in {"persona", "user", "profile", "facts", "preferences"}]
    persona_text = "\n".join([f"- {block.get('value', '')}" for block in persona_blocks if block.get("value")])
    goals_lines = [f"- {r.get('value', '')}" for r in rel if r.get("label") == "goals" and r.get("value")]
    goals_text = "\n".join(goals_lines)
    try:
        ctx_pack = mem.retrieve_context(last_user or "", budget_tokens=int(os.getenv("MEMORY_BUDGET_TOKENS", "1024")))
    except Exception:
        ctx_pack = {"working": {"summary": ""}, "long_term": []}
    working_summary = (ctx_pack.get("working", {}) or {}).get("summary") or ""
    long_term_entries = ctx_pack.get("long_term") or []
    long_term_text = "\n".join([f"- {item.get('value', '')[:180]}" for item in long_term_entries[:6] if item.get("value")])
    return {
        "persona": persona_text,
        "goals": goals_text,
        "working": working_summary,
        "long_term": long_term_text,
    }


async def _generate_reply(run: AgentRuntime, last_user: Optional[str]) -> str:
    ctx = _gather_prompt_context(run, last_user)
    affect_line = run.ee.to_prompt()
    base_system = (
        "You are Nova, a friendly companion. Keep context coherent and grounded.\n"
        "Anchor your reply to the user's latest message; do not change topics.\n"
        "Use memory only if directly relevant; otherwise, do not bring up unrelated facts.\n"
        "Ask at most one short question when it helps.\n"
        "Tone: concise, warm; avoid filler or forced hype.\n"
    )
    system_seed = base_system
    if affect_line:
        system_seed += "\n" + affect_line
    if ctx["persona"]:
        system_seed += f"\nPersona and facts:\n{ctx['persona']}"
    if ctx["goals"]:
        system_seed += f"\nCurrent goals:\n{ctx['goals']}"
    if ctx["working"]:
        system_seed += f"\nWorking summary:\n{ctx['working']}"
    if ctx["long_term"]:
        system_seed += f"\nLong-term memory:\n{ctx['long_term']}"

    messages = [{"role": "system", "content": system_seed}] + run.truncated_history()
    try:
        if hasattr(run.llm, "generate_from_messages"):
            return run.llm.generate_from_messages(messages)  # type: ignore[attr-defined]
        user_prompt = "\n\n".join([f"{m['role']}: {m['content']}" for m in messages if m['role'] != 'system'])
        return run.llm.generate(system_seed, user_prompt)
    except Exception as exc:  # noqa: BLE001
        return f"(error) generation failed: {exc}"


async def handle_turn(run: AgentRuntime, user_text: str, *, play_override: Optional[bool] = None) -> str:
    user_text = (user_text or "").strip()
    if not user_text:
        raise ValueError("user_text must not be empty")

    run.history.append({"role": "user", "content": user_text})
    try:
        run.ee.appraise_from_text(user_text)
    except Exception:
        pass

    direct = None
    try:
        direct = try_direct_memory_answer(run.mem, user_text)
    except Exception:
        direct = None

    if direct:
        utterance = direct
    else:
        utterance = await _generate_reply(run, user_text)
        if run.tools is not None:
            try:
                action = run.tools.parse_action(utterance)
                if action:
                    observation = run.tools.dispatch(action)
                    tool_ctx = f"Tool '{action.name}' result:\n{observation.text}"
                    run.history.append({"role": "user", "content": tool_ctx})
                    utterance = await _generate_reply(run, user_text)
            except Exception:
                pass

    run.history.append({"role": "assistant", "content": utterance})
    sentiment = analyze_text_sentiment(utterance)
    safe_print(f"[assistant:{sentiment.label}] {utterance}")

    run.auto_mem.llm = run.llm
    try:
        ctx_pack = run.mem.retrieve_context(user_text, budget_tokens=int(os.getenv("MEMORY_BUDGET_TOKENS", "1024")))
    except Exception:
        ctx_pack = {"working": {"summary": ""}, "long_term": []}
    working_summary = (ctx_pack.get("working", {}) or {}).get("summary") or ""
    try:
        info = run.auto_mem.process_turn(user_text, utterance, working_summary)
        stored = int(info.get("stored", 0))
        details = info.get("stored_items") or []
        if stored or run.auto_mem.cfg.verbose:
            if details:
                preview = "; ".join(details[:3])
                safe_print(f"[memory] +{stored}: {preview}")
            else:
                safe_print(f"[memory] +{stored} item(s)")
    except Exception as exc:
        safe_print(f"[memory:auto] failed: {exc}")

    try:
        run.mem.log_interaction(user_text, utterance)
        captures = run.mem.try_autocapture(user_text) or []
        if captures:
            preview = "; ".join([f"{label}: {value}" for label, value in captures][:3])
            safe_print(f"[memory:heuristic] {preview}")
    except Exception:
        pass

    wav_path = None
    try:
        wav_path = await synthesize(run.cfg, utterance)
        if wav_path:
            safe_print(f"[tts] Wrote {wav_path}")
    except Exception as exc:
        safe_print(f"[tts] synthesis failed: {exc}")
        wav_path = None

    if wav_path:
        tts_cfg = run.cfg.get("tts", {})
        play_async = bool(tts_cfg.get("play_async", False))
        auto_play_cfg = bool(tts_cfg.get("auto_play", False))
        should_play = play_override if play_override is not None else auto_play_cfg
        if should_play:
            try:
                import winsound

                flags = winsound.SND_FILENAME
                if play_async:
                    flags |= winsound.SND_ASYNC
                winsound.PlaySound(str(wav_path), flags)
            except Exception as exc:
                safe_print(f"[tts] Playback failed: {exc}")

    run.turn_count += 1
    if run.turn_count % 10 == 0:
        try:
            stats = run.mem.consolidate()
            if (stats.get("merged") or 0) > 0:
                safe_print(f"[memory] consolidated: {stats}")
        except Exception:
            pass

    return utterance


async def run_once(cfg: Dict[str, Any], text: str, *, play: bool = False) -> None:
    runtime = AgentRuntime(cfg)
    try:
        await handle_turn(runtime, text, play_override=play)
    finally:
        pass


async def run_continuous(cfg: Dict[str, Any], *, play: bool = False) -> None:
    runtime = AgentRuntime(cfg)
    safe_print("[continuous] Type a message (/quit to exit, /search <query> to web search).")
    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        lowered = user_input.lower()
        if lowered in {"/quit", ":q", "exit", "quit"}:
            break
        if user_input.startswith("/search "):
            query = user_input[len("/search "):].strip()
            if not query:
                safe_print("[search] usage: /search your query")
                continue
            try:
                payload = await search_and_extract(query, num_results=6)
                ctx_block = pack_for_context(payload, max_pages=3, per_page_chars=1200)
                safe_print(f"[search]\n{ctx_block}")
                runtime.history.append({"role": "user", "content": f"Search results for '{query}':\n{ctx_block}"})
            except Exception as exc:
                safe_print(f"[search] failed: {exc}")
            continue
        try:
            await handle_turn(runtime, user_input, play_override=play)
        except Exception as exc:
            safe_print(f"[agent] error: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Neuro MVP agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", type=str, help="Run a single-turn response for the provided text")
    group.add_argument("--continuous", action="store_true", help="Start an interactive chat loop")
    parser.add_argument("--play", action="store_true", help="Force audio playback regardless of config")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()
    if args.text:
        asyncio.run(run_once(cfg, args.text, play=args.play))
    else:
        asyncio.run(run_continuous(cfg, play=args.play))


if __name__ == "__main__":
    main()
