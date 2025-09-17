Neuro MVP — Agent Guide
=======================

Local-first AI companion that chats, remembers, speaks, and animates a VTube Studio avatar. Runs on Windows with minimal setup; memory is private and stored on disk (SQLite). Vision and web search are optional.

What’s Included
---------------
- LLM/VLM: Qwen via Transformers or any OpenAI-compatible server (LM Studio, vLLM, Ollama, LocalAI).
- Memory: Lightweight RAG via Qdrant (remote vector DB) or local SQLite fallback.
- TTS: Piper (offline) or Edge-TTS.
- Avatar: VTube Studio hotkeys via websocket.
- Affect: Text/audio sentiment + simplified OCC emotion engine.
- Tools: Web search (Serper), file indexing, memory dashboard and CLI.

Quick Start (Windows)
---------------------
1) Create a venv and install deps

   - PowerShell in repo root:
     - `py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1`
     - `powershell -File scripts\install_deps.ps1`

1a) (Optional) Local embeddings/reranker

   - `pip install sentence-transformers`

2) Set up Piper TTS (optional, recommended)

   - `powershell -File scripts\setup_piper.ps1`
   - This downloads `tools/piper/piper/piper.exe` and a default English voice.

3) Configure environment and defaults

   - Copy `.env.example` to `.env` and edit values (Piper paths, VTS URL, optional SERPER key).
   - Configure Clerk server-side verification: set `CLERK_ISSUER` (and optionally `CLERK_JWKS_URL`, `CLERK_JWT_AUDIENCE`). Frontend requests must send the Clerk session token as `Authorization: Bearer …`.
   - To use Qdrant Cloud/on-prem, set in `.env`:
     - `MEMORY_PROVIDER=qdrant`
     - `QDRANT_URL=...` and `QDRANT_API_KEY=...`
     - Optionally `QDRANT_COLLECTION=memory_items`, `QDRANT_DIM`, `QDRANT_DISTANCE`
   - If using sentence-transformers locally for embeddings, set `EMBEDDING_MODEL=...` (dimension should match `QDRANT_DIM`).
   - Review and adjust `config.yaml` (models, memory, TTS, VTS mappings).

3a) Start the Mem0 memory bridge (Qdrant-backed)

   - First-time setup:
     - `cd mem0-service`
     - `npm install`
     - Copy `.env.example` to `.env` and fill in `QDRANT_URL`, `QDRANT_API_KEY`, etc.
   - Run the service (auto-reload): `npm run dev`
   - Prod-style run: `npm start` or `node server.js`
   - Service listens on `http://127.0.0.1:4040` (override with `MEM0_BASE_URL`). Ensure it’s running before launching the agent.

3b) Set up Clerk front-end (Vite + Clerk JS)

   - `cd web/clerk-app`
   - `npm install`
   - Copy `.env.example` to `.env` and set `VITE_CLERK_PUBLISHABLE_KEY`.
   - `npm run dev` to launch the Clerk auth UI (http://localhost:5173).
   - After signing in, use the “Copy session token” button and send it as `Authorization: Bearer <token>` when calling the Flask API.

   - First-time setup:
     - `cd mem0-service`
     - `npm install`
     - Copy `.env.example` to `.env` and fill in `QDRANT_URL`, `QDRANT_API_KEY`, etc.
   - Run the service (auto-reload): `npm run dev`
   - Prod-style run: `npm start` or `node server.js`
   - Service listens on `http://127.0.0.1:4040` (override with `MEM0_BASE_URL`). Ensure it’s running before launching the agent.

4) Initialize memory (persona, user)

   - `powershell -File scripts\init_memory_db.ps1 -- --user-label "User is Noah." --persona "You are Lyra …" --index`
   - This seeds persona/user and indexes project docs into “general” memory.
   - This seeds persona/user and (optionally) indexes project docs into memory. With `qdrant`, points are stored in your Qdrant collection.

5) Run the agent

   - One-shot: `powershell -File scripts\run_agent.ps1 -- --text "Hello!"`
   - Interactive: `powershell -File scripts\run_agent.ps1 -- --continuous`

Runtime Overview
----------------
Per turn flow (interactive mode):

1) Read user input (or self-drive if enabled).
2) Affect: update emotion engine using text sentiment.
3) Memory retrieve: persona/user blocks, working summary, top-K long-term items.
4) Direct memory QA: answer simple profile/preference questions (e.g., “What is my favorite food?”) from stored memory without calling the LLM.
5) LLM/VLM: generate reply using system prompt + retrieved context.
6) Memory write: log episodic summary; extract and store concise facts/goals via auto-memory.
7) TTS: synthesize to WAV (Piper/Edge) and optionally play.
8) VTS: trigger expression hotkeys mapped from sentiment/arousal.

Key Entry Points
----------------
- `run_agent.py`: main entry (single-turn or `--continuous`).
  - Builds system prompt from persona, user facts, goals, working summary, long-term memory, and affect.
  - Integrates direct memory QA for “favorite X” style questions before LLM generation.
  - Logs turns and runs auto memory extraction.
  - Handles TTS output and VTS hotkeys.

- `src/neuro_mvp/memory.py`: `MemoryClient` facade.
  - Providers: `local` (SQLite) or `stub`.
  - Read: `search(...)` for block view; `retrieve_context(...)` for full pack; `find_items(...)` for keyword queries.
  - Write: `write(label, value)`, `log_interaction(user, assistant)`.
  - Heuristics: `try_autocapture(...)` captures “my favorite X is Y”, names, likes, pronouns, location.

- `src/neuro_mvp/memory_qdrant.py`: Qdrant-backed memory implementation (vectors + payloads).
- `src/neuro_mvp/memory_local.py`: local implementation (SQLite + FTS5/optional FAISS).

- `src/neuro_mvp/memory_auto.py`: LLM-assisted extraction of concise facts/goals; respects importance threshold and label routing.

- LLMs/VLMs
  - `src/neuro_mvp/openai_compat.py`: Chat Completions against `OPENAI_BASE_URL` (LM Studio etc.).
  - `src/neuro_mvp/qwen.py`: Local Qwen models via Transformers; disables on CPU if `cpu_safe=true`.

- TTS
  - `src/neuro_mvp/tts_kokoro.py`: Piper executable; post-process to 48kHz mono 16-bit WAV.
  - Edge-TTS async fallback.

- Avatar (VTube Studio)
  - `src/neuro_mvp/vts.py`: Token creation and websocket auth; hotkey triggers.
  - Hotkeys mapped from sentiment/arousal in `config.yaml`.

- Sentiment & Emotion
  - `src/neuro_mvp/sentiment.py`: VADER text sentiment; audio arousal via RMS (offline) or SER model.
  - `src/neuro_mvp/emotion.py`: simplified OCC engine; state stored in DB; included in prompt.

- Web Search
  - `src/neuro_mvp/web_search_tool.py`: Serper search + content extraction (trafilatura fallback); pack results for context.

Memory Model & Usage
--------------------
Labels and routing:

- `persona` (global): agent’s persona text.
- `user`: label like “User is Noah.” (selects/creates active user id).
- `profile`: stable user facts; `preferences`: likes/favorites; `facts`: semantic facts; `goals`: user/assistant goals.
- `episodic`: rolling conversation summaries; `general`: indexed docs (global).

Where data lives:

- Local SQLite database at `MEMORY_DB_PATH` (e.g., `.data/memory.sqlite`).
- Collections: `memory_items` (vectors + metadata), `working_summary`, `sessions`, `emotion_state`, `emotion_events`, `tool_logs`.
  If using embeddings, ensure your model fits your retrieval config.

Reading memory:

- Blocks: `MemoryClient.search(query)` returns persona/user/facts/preferences/goals blocks for prompts.
- Context pack: `MemoryClient.retrieve_context(query, budget_tokens)` returns persona, user, working summary, and top-K long-term items.
- Keyword: `MemoryClient.find_items(query, labels=[...], limit=...)` queries items via LIKE/FTS.

Writing memory:

- Automatic:
  - `log_interaction(user, assistant)` appends an episodic summary and updates the working summary.
  - `MemoryAutoUpdater.process_turn(...)` proposes concise entries (JSON) and persists those over threshold.
  - `try_autocapture(text)` stores simple facts like names, location, likes, and “my favorite X is Y”.

- Manual (CLI):
  - Set persona: `python tools/memory_cli.py set-persona --text "..."`
  - Set/select user: `python tools/memory_cli.py set-user-label --text "User is Noah."`
  - Add item: `python tools/memory_cli.py add --label preferences --value "favorite food: sushi"`
  - Forget: `python tools/memory_cli.py forget-last-session` | `forget-by-label --label preferences` | `wipe-user`
  - Index files: `python tools/memory_cli.py index-files` (writes to `general` when enabled)

Direct Memory QA (Favorites)
----------------------------
- The agent can answer “What is my favorite X?” directly from memory.
  - Looks for “favorite X: Y” or “favorite X is Y” in `preferences`/`profile`/`facts`.
  - If none, suggests from “I like …” mentions and asks for confirmation.
- Teach it naturally: “My favorite food is sushi.” (auto-captured), or add via CLI as above.

Configuration
-------------
- `.env` overrides common paths and keys (copy from `.env.example`). Important variables:
  - VTS: `VTS_URL`, `VTS_PLUGIN_NAME`, `VTS_DEVELOPER`.
  - TTS (Piper): `PIPER_EXE`, `PIPER_VOICE`, `PIPER_CONFIG`.
  - Memory: `MEMORY_PROVIDER=local`, `MEMORY_DB_PATH`, `MEMORY_TOP_K`, `MEMORY_WORKING_TURNS`, `MEMORY_BUDGET_TOKENS`.
  - Embeddings/Reranker (optional): `EMBEDDING_MODEL`, `RERANKER_MODEL`.
  - Web search: `SERPER_API_KEY` (optional).
  - HF offline: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HOME=...`.

- `config.yaml` tunes behavior without touching code:
  - `models`: pick OpenAI-compatible server or local Transformers; set device/cpu_safe.
  - `memory`: provider (`local` default), persona, user_label, auto extraction thresholds, consolidation settings.
  - `tts`: engine and output options.
  - `vts`: websocket URL, token path, hotkey maps for sentiment/arousal.
  - `conversation`: window size, require_input vs self-drive logging.

VTube Studio Integration
------------------------
- On first run, the agent requests an authentication token and saves it to `.vts_token.json`.
- Map hotkeys in VTS to emotion names in `config.yaml` under `vts.sentiment_map` and `vts.arousal_map`.
- The agent triggers hotkeys after generating speech and analyzing valence/arousal.

TTS
---
- Piper (default): fast and offline. Configure executable and voice files.
- Edge-TTS: simple online fallback if Piper is not configured.
- Output WAV is normalized to 48 kHz mono 16-bit for consistent playback and downstream tools.

Web Search Tool (Optional)
--------------------------
- Uses Serper (set `SERPER_API_KEY`).
- Fetches pages concurrently and extracts clean text (trafilatura if available; otherwise basic cleanup).
- `pack_for_context(...)` formats results for inclusion in the prompt.

Emotion Engine & Sentiment
--------------------------
- Text sentiment via VADER (fast, local); audio arousal via RMS or a local SER model.
- Emotion engine synthesizes an OCC-inspired state and adds a one-line “Affect:” note to the system prompt.
- Emotion state and events are recorded in the DB (visible in the dashboard).

Dashboard
---------
- `python tools/memory_dashboard.py` (Flask app; default port 8765).
  
- Views: Persona, Working summary, Long-term items (profile/preferences/facts/goals), General docs, Conversation (episodic), Tools, and Emotion.
- Delete by keyword across labels with optional inclusion of global (`general/persona`) items.

Lyra Web UI (3D Avatar Stage)
-----------------------------
- A separate, static demo UI under `web/lyra` for showcasing a 3D avatar (GLB) with a Zoom-like layout.
- Run a static server (Python `http.server` or `npx http-server`) and open http://localhost:5500/.
- Drag-and-drop a `.glb` or auto-load from `web/lyra/assets/`.

Troubleshooting
---------------
- LLM doesn’t respond on CPU: `cpu_safe: true` disables local model loading on CPU. Use `openai_compat` with LM Studio or set `cpu_safe: false` and provide a local Transformers model.
- Piper errors: re-run `scripts/setup_piper.ps1` and verify `PIPER_EXE`, `PIPER_VOICE`, `PIPER_CONFIG` in `.env`/`config.yaml`.
- VTS auth fails: ensure VTS is running and `VTS_URL` is correct (default `ws://127.0.0.1:8001`). Delete `.vts_token.json` to re-auth.
- No search results: set `SERPER_API_KEY` or disable web search paths.
- Memory not updating: confirm `memory.auto.enable` and importance threshold in `config.yaml`.
- Strict offline: set `HF_HUB_OFFLINE=1` and use local model folders in `config.yaml`.

Extending the Agent
-------------------
- Add tools: implement a function/module and log tool usage via `LocalRAGMemory.log_tool(...)` for visibility in the dashboard.
- New memory patterns: update `MemoryClient.try_autocapture(...)` or enrich `MemoryAutoUpdater` prompt/mapper.
- Retrieval quality: configure `EMBEDDING_MODEL` and `RERANKER_MODEL`.
- Vision: enable VLM under `models.vlm` with a local Qwen-VL model path (Transformers) or a compatible server.

File Map (Where to Look)
------------------------
- Agent entry: `run_agent.py`
- Memory facade: `src/neuro_mvp/memory.py`
 
- Legacy local store: `src/neuro_mvp/memory_local.py`
- Auto memory: `src/neuro_mvp/memory_auto.py`
- TTS: `src/neuro_mvp/tts_kokoro.py`
- VTS: `src/neuro_mvp/vts.py`
- LLMs: `src/neuro_mvp/openai_compat.py`, `src/neuro_mvp/qwen.py`
- Sentiment/Affect: `src/neuro_mvp/sentiment.py`, `src/neuro_mvp/emotion.py`
- Web search: `src/neuro_mvp/web_search_tool.py`
- Dashboard/CLI: `tools/memory_dashboard.py`, `tools/memory_cli.py`, `tools/init_memory_db.py`
- Config: `.env`, `config.yaml`
- D:/NewNeuro/.venv/Scripts/Activate.ps1
License & Privacy
-----------------
- Memory and persona are stored locally by default. No memory is sent to external services unless you configure an external LLM/VLM or search API.
- Check third-party model/data licenses (voices, models, Serper) when enabling them.


