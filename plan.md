# MVP Launch Plan

## 1. Provision & Configure Core Services
- **Goal:** Stand up the external services Lyra depends on.
  - Provision a Qdrant cluster (or self-hosted instance) and note `QDRANT_URL`, `QDRANT_API_KEY`, collection name, and vector dims.
  - Run the Mem0 Node bridge locally with `npm run dev`, confirm `/health` responds, and point `MEM0_BASE_URL` at it.
  - Gather Clerk publishable/server keys, JWKS URL, and audience so token verification can succeed.
  - Decide how embeddings/LLMs will be served (Ollama vs. LM Studio) and set the corresponding API base URLs/keys for both Flask and Mem0.

## 2. Configure Local Environment
- **Goal:** Ensure the Python/Node apps share consistent configuration.
  - Copy `.env.example` to `.env`, then populate Clerk, Qdrant, Mem0, Kokoro, and search API keys.
  - Create a Python 3 venv, activate it, and `pip install -r requirements.txt`.
  - Install Node dependencies in `mem0-service/` and verify `npm run dev` starts cleanly.
  - Set Kokoro env vars (`KOKORO_VOICE`, `KOKORO_LANG`) and confirm the worker warm-up completes without errors.

## 3. Seed Persona & Memory Baseline
- **Goal:** Load starting persona/user context so conversations feel grounded.
  - Use `tools/init_memory_db.py` (and/or `.env` values) to write persona + user label into Mem0/Qdrant.
  - Run any seeding scripts needed for general/project knowledge once Mem0 is live.
  - Verify `MemoryClient.ensure_agent` succeeds by checking the `mem0-service` logs.

## 4. Backend/Agent Wiring
- **Goal:** Validate request flow through Flask, WebAgentSession, and the LLM.
  - Enable the desired LLM in `config.yaml` (`models.llm.enable` and `id/base_url`).
  - Start `python web/server.py` and hit `/api/chat` as a guest to confirm quota increments and responses stream back.
  - Authenticate via Clerk (token from the Clerk widget) and ensure `/api/chat/stream` works while bypassing guest limits.
  - Confirm Kokoro TTS responses return audio from `/api/tts` for signed-in users.

## 5. Frontend Chat & Voice Experience
- **Goal:** Exercise both UIs against the running backend.
  - Load `web/index.html`, trigger Clerk sign-in, and test guest messaging until `GUEST_MESSAGE_LIMIT` is reached.
  - Verify streaming deltas render in the chat window and continuous mode toggles `session.start_continuous()`.
  - Open `/voice`, confirm microphone permissions, send speech-to-text → `/api/chat` → `/api/tts` loop, and validate playback.
  - Check emotion polling via `/api/emotion` updates the UI card in real time.

## 6. Memory Quality & Monitoring
- **Goal:** Ensure important facts persist and retrieval packs are rich.
  - Chat through scenarios that should trigger `MemoryAutoUpdater.process_turn` and watch console logs for stored items.
  - Inspect Qdrant (via dashboard CLI or `tools/memory_dashboard.py`) to confirm labels (`profile`, `preferences`, `facts`, `goals`).
  - Tune auto-memory thresholds (`importance_threshold`, `max_items`) in `config.yaml` if noise creeps in.
  - Run consolidation/promote scripts once Mem0 has data to keep memories clean.

## 7. Tooling & Autonomy Loop
- **Goal:** Validate agent tools and continuous behavior.
  - From `run_agent.py --continuous`, trigger `/search` commands to confirm Brave/Serper integration.
  - Exercise `Controller.choose_action` paths and ensure tool outputs are logged without crashing the loop.
  - Confirm `session.start_continuous()` self-continues after the idle timeout without user input.

## 8. Testing & QA
- **Goal:** Catch regressions before deploy.
  - Run `python -m pytest` and fix any failing tests (`test_server_endpoints`, `test_memory_auto`, etc.).
  - Manually hit edge cases: missing guest ID, invalid Clerk token, Mem0 offline, TTS failure.
  - Capture smoke-test scripts (curl/Postman) for `/api/chat`, `/api/chat/stream`, `/api/tts`, `/api/auth/config`.

## 9. Deployment Readiness
- **Goal:** Prepare for public MVP launch.
  - Package the Flask API for a target host (Render/Fly/Railway), set env vars, and verify HTTPS access.
  - Deploy `web/` to Vercel (or equivalent) and configure `BACKEND_URL` + Clerk publishable key on the frontend.
  - Re-point Mem0/Qdrant credentials to production instances and rerun quick smoke tests.
  - Review the top-level README deployment checklist and document any environment-specific notes in your own runbook.
