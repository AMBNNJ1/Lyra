import argparse
import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.neuro_mvp.agent_loop import Controller, build_tool_registry
from src.neuro_mvp.config import load_config, get_memory_config, get_llm_config, get_tts_config
from dotenv import load_dotenv
from src.neuro_mvp.emotion import EmotionEngine
from src.neuro_mvp.exceptions import LLMError, TTSError, MemoryError
from src.neuro_mvp.memory import MemoryClient
from src.neuro_mvp.memory_auto import AutoMemoryConfig, MemoryAutoUpdater
from src.neuro_mvp.memory_utils import try_direct_memory_answer
from src.neuro_mvp.openai_compat import ChatLLMConfig, OpenAIChatLLM
from src.neuro_mvp.qwen import LLMConfig, QwenLLM
from src.neuro_mvp.sentiment import analyze_text_sentiment
# VOICE_MODE_DISABLED: TTS import commented out
# from src.neuro_mvp.tts_kokoro import KokoroTTS
from src.neuro_mvp.utils import safe_print
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


# Memory answer function moved to memory_utils.py


# Configuration and utility functions moved to config.py and utils.py


# VOICE_MODE_DISABLED: TTS synthesize function commented out
# async def synthesize(cfg: Dict[str, Any], text: str) -> Optional[Path]:
#     """Synthesize text to speech using Kokoro TTS."""
#     tts_cfg = get_tts_config()
#     if not tts_cfg.get("enable", False):
#         return None
#
#     kokoro_cfg = tts_cfg.get("kokoro", {})
#     voice = kokoro_cfg.get("voice", "af_heart")
#     lang = kokoro_cfg.get("lang", "a")
#     out_path = Path(kokoro_cfg.get("out_path", "response.wav"))
#
#     try:
#         tts = KokoroTTS(lang_code=lang, voice=voice)
#         tts.synthesize_to_wav(text, str(out_path))
#         return out_path
#     except Exception as e:
#         raise TTSError(f"TTS synthesis failed: {e}") from e


class AgentRuntime:
    """Simplified agent runtime with centralized configuration."""
    
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.history: List[Dict[str, str]] = []
        self.turn_count = 0
        
        # Initialize components
        self.mem = self._init_memory()
        self.ee = self._init_emotion_engine()
        self.llm = self._init_llm()
        self.auto_mem = self._init_auto_memory()
        self.tools = self._init_tools()
    
    def _init_memory(self) -> MemoryClient:
        """Initialize memory client with configuration."""
        mem_cfg = get_memory_config()
        provider = mem_cfg.get("provider", "mem0").lower()

        try:
            mem = MemoryClient(provider=provider)
            mem0_cfg = mem_cfg.get("mem0", {})
            persona = mem0_cfg.get("persona", "Nova is friendly.")
            user_label = mem0_cfg.get("user_label", "User is Sam.")
            mem.ensure_agent(persona=persona, user_label=user_label, model=None, embedding=None)
            return mem
        except Exception as e:
            raise MemoryError(f"Failed to initialize memory: {e}") from e
    
    def _init_emotion_engine(self) -> EmotionEngine:
        """Initialize emotion engine."""
        ee = EmotionEngine()
        ee.add_goal("help_user", 1.0)
        return ee
    
    def _init_llm(self):
        """Initialize LLM with configuration."""
        llm_cfg = get_llm_config()
        provider_name = llm_cfg.get("provider", "openai_compat").lower()
        
        try:
            if provider_name in {"openai", "openai_compat", "lmstudio"}:
                chat_cfg = ChatLLMConfig(
                    base_url=llm_cfg.get("base_url", "http://localhost:1234/v1"),
                    model=llm_cfg.get("id", "qwen2.5-3b-instruct"),
                    max_new_tokens=int(llm_cfg.get("max_new_tokens", 128)),
                    temperature=float(llm_cfg.get("temperature", 0.7)),
                    api_key=llm_cfg.get("api_key"),
                )
                return OpenAIChatLLM(chat_cfg)
            else:
                qwen_cfg = LLMConfig(
                    model_id=llm_cfg.get("id", "Qwen/Qwen3-8B"),
                    max_new_tokens=int(llm_cfg.get("max_new_tokens", 128)),
                    temperature=float(llm_cfg.get("temperature", 0.7)),
                    thinking=bool(llm_cfg.get("thinking", False)),
                    device=self.cfg.get("models", {}).get("device", "auto"),
                    cpu_safe=bool(self.cfg.get("models", {}).get("cpu_safe", True)),
                )
                return QwenLLM(qwen_cfg)
        except Exception as e:
            raise LLMError(f"Failed to initialize LLM: {e}") from e
    
    def _init_auto_memory(self) -> MemoryAutoUpdater:
        """Initialize auto memory updater."""
        mem_cfg = get_memory_config()
        auto_cfg = AutoMemoryConfig(
            enable=bool(mem_cfg.get("auto", {}).get("enable", True)),
            importance_threshold=int(mem_cfg.get("auto", {}).get("importance_threshold", 6)),
            max_items=int(mem_cfg.get("auto", {}).get("max_items", 4)),
            store_self_facts=True,
            store_user_facts=True,
            allow_general_from_auto=bool(mem_cfg.get("auto", {}).get("allow_general_from_auto", False)),
            verbose=bool(mem_cfg.get("auto", {}).get("verbose", False)),
        )
        return MemoryAutoUpdater(self.mem, llm=None, cfg=auto_cfg)
    
    def _init_tools(self) -> Optional[Controller]:
        """Initialize tools controller."""
        try:
            return Controller(self.llm, self.mem, build_tool_registry(self.mem))
        except Exception:
            return None

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
    except Exception as e:
        safe_print(f"[emotion] Failed to appraise text: {e}")

    direct = None
    try:
        direct = try_direct_memory_answer(run.mem, user_text)
    except MemoryError as e:
        safe_print(f"[memory] Failed to get direct answer: {e}")
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
    except MemoryError as e:
        safe_print(f"[memory] Failed to retrieve context: {e}")
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

    # VOICE_MODE_DISABLED: TTS synthesis and playback commented out
    # wav_path = None
    # try:
    #     wav_path = await synthesize(run.cfg, utterance)
    #     if wav_path:
    #         safe_print(f"[tts] Wrote {wav_path}")
    # except TTSError as e:
    #     safe_print(f"[tts] synthesis failed: {e}")
    #     wav_path = None
    #
    # if wav_path:
    #     tts_cfg = run.cfg.get("tts", {})
    #     play_async = bool(tts_cfg.get("play_async", False))
    #     auto_play_cfg = bool(tts_cfg.get("auto_play", False))
    #     should_play = play_override if play_override is not None else auto_play_cfg
    #     if should_play:
    #         try:
    #             import winsound
    #
    #             flags = winsound.SND_FILENAME
    #             if play_async:
    #                 flags |= winsound.SND_ASYNC
    #             winsound.PlaySound(str(wav_path), flags)
    #         except Exception as exc:
    #             safe_print(f"[tts] Playback failed: {exc}")

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
