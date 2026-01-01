Lyra Agent Guide
================

Lyra is a web-based companion: visitors land on a Clerk-gated chat page with a looping avatar video and can optionally switch to a voice experience. This document explains how conversations travel through the stack so you can extend or debug the system quickly.

System Overview
---------------

```
Browser (chat or voice) ? Clerk JS ? Flask API ? Mem0 service
                                 ? Kokoro TTS ? Emotion engine ? Web search
```

1. **Authentication**
   - The chat page fetches `/api/auth/config` to learn the Clerk publishable key.
   - Clerk JS mounts the sign-in widget. Signed-in sessions yield a token that the frontend forwards via `Authorization: Bearer ...`.
   - The Flask API verifies tokens with `ClerkVerifier` and falls back to a short guest quota when none is provided.

2. **Conversation Loop** (handled in `web/server.py` + `src/neuro_mvp`)
   - Request enters `api/chat` (JSON) or `api/chat/stream` (SSE).
   - `MemoryClient` pulls persona, user profile, and recent context from Mem0.
   - `MemoryAutoUpdater` watches each turn to extract new facts/goals and writes them back through Mem0.
   - `EmotionEngine` appraises user text to tag the current affect line that feeds the LLM prompt and optionally the avatar.
   - Replies stream back to the browser; the voice page also calls `/api/tts` to render audio via Kokoro.

3. **Storage**
   - Mem0 service (Node) handles memory persistence. Configure its `.env` as needed.
   - Items are labeled (`profile`, `preferences`, `facts`, `goals`, `general`) so retrieval can build tailored prompt sections.

Primary Components
------------------

- `web/server.py`
  - `/api/chat` & `/api/chat/stream` ? orchestrate memory retrieval, emotion scoring, and LLM streaming.
  - `/api/auth/config` ? exposes the publishable key to the frontend.
  - `/api/tts` ? synthesizes voice replies with Kokoro.
  - `/voice`, `/landing`, `/` ? serve static pages.

- `src/neuro_mvp/memory.py`
  - Client facade for Mem0.
  - `retrieve_context(query)` assembles persona, user, working summary, and long-term snippets.

- `src/neuro_mvp/memory_auto.py`
  - Prompts an LLM (or heuristic fallback) to extract concise memories after every turn.
  - Filters by importance threshold and label before writing.

- `src/neuro_mvp/emotion.py`
  - OCC-style engine that tracks joy/fear/etc. and emits a human-readable reason.

- `src/neuro_mvp/web_search_tool.py`
  - Optional Brave/Serper search integration returning structured blocks for grounding answers.

Voice Flow
----------

The voice page reuses the same backend endpoints but swaps the input/output UX:

1. Browser speech recognition captures the user utterance.
2. `/api/chat` returns a text reply; `/api/tts` streams synthesized audio.
3. UI disables the mic when guest credits expire and prompts the user to sign in with Clerk.

Testing & Diagnostics
---------------------

- `python -m pytest` ? runs backend unit tests (Clerk verifier, memory helpers, auto memory, search utilities, API guest gating).
- `tools/memory_dashboard.py` ? inspect what Mem0 has stored for a given user.
- `tools/memory_cli.py` ? quick CRUD for memories when debugging.

Extending Lyra
--------------

- **LLM swap** ? adjust `config.yaml` (`models.llm`) to point at a different OpenAI-compatible endpoint.
- **Avatar actions** ? build on the emotion output to trigger additional animations or LED cues in the UI.
- **New tools** ? register Python callables in `src/neuro_mvp/agent_loop.py` and surface them via the chat UI.
- **Memory tuning** ? change `AutoMemoryConfig` thresholds or extend `_map_type_to_label` to categorize new facts.

This guide plus the updated README, `memory.md`, and `task.md` should give you everything needed to evolve Lyra into a richer companion experience.
