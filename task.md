# AI VTuber MVP — Execution Plan (Task List)

This is a pragmatic, acceptance-driven checklist to build the MVP described in `agent.md`. Steps are arranged to minimize rework, surface risks early, and keep feedback loops tight. Each step has a “Done When” gate and notes on pitfalls or alternatives. Follow in order unless a step says it can be parallelized.

Audience: Single developer on Windows with an NVIDIA GPU. Adapt paths and commands as needed.

---

## 0) Decisions & Prereqs

- Decide memory backend:
  - Option A: Letta Cloud (managed, requires account + API key).
  - Option B: Local MemGPT (open source, self-hosted service).
- Decide TTS:
  - Option A: Edge-TTS (simple, needs network).
  - Option B: Piper (offline, install voice model).
- Install VTubeStudio and have a Live2D model ready.
- Confirm GPU VRAM and CUDA version. Target: ≥16 GB VRAM for both models, else plan quantization or smaller models.

Done When
- You have chosen memory + TTS options and can log into VTS.

---

## 1) Workspace & Environment

- Create a new Conda env (or venv) for isolation.
- Ensure Python 3.10 (per guide; 3.11 often works but stick to 3.10 for libs like decord).
- Create `requirements.txt` with core deps (or use `pip install` directly first, then freeze later).

Commands (PowerShell)
- conda create -n ai_vtuber python=3.10 -y
- conda activate ai_vtuber

Done When
- `python --version` shows 3.10.x and `pip` works in the active env.

---

## 2) Install GPU Stack & Libraries

- Install the correct PyTorch build for your CUDA.
- Install Transformers/Accelerate, qwen-vl-utils, websockets/pyvts, and your TTS libs.

Commands
- pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
- pip install git+https://github.com/huggingface/transformers accelerate
- pip install "qwen-vl-utils[decord]==0.0.8"
- pip install pyvts websockets
- For TTS: pip install edge-tts (or Piper’s required packages)
- If using Letta: pip install letta-client

Done When
- `python -c "import torch; print(torch.cuda.is_available())"` prints True
- `python -c "import transformers, qwen_vl_utils"` runs without errors

Pitfalls
- Wrong CUDA wheel → `torch.cuda.is_available()` False. Match CUDA version to your GPU driver. Consider `pip install --index-url` variants for other CUDA versions.

---

## 3) GPU Sanity Check

- Run a quick CUDA smoke test.

Command
- python - <<'PY'
import torch
print("CUDA:", torch.cuda.is_available())
print("Device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU")
PY

Done When
- Reports a valid GPU name and CUDA=True.

---

## 4) VLM (Qwen2.5‑VL) Minimal Test

- Load `Qwen/Qwen2.5-VL-7B-Instruct` and describe a public image URL.
- Use the snippet in `agent.md` (4.1) to verify decoding works.

Done When
- The script prints a reasonable textual description of the image, and GPU memory usage increases briefly.

Pitfalls
- OOM on load → reduce `max_new_tokens`, close other GPU apps, or plan quantization later.

---

## 5) LLM (Qwen3‑8B) Minimal Test

- Load `Qwen/Qwen3-8B` and run a simple chat turn.
- Use the snippet in `agent.md` (4.2) and confirm output.

Done When
- The script prints a coherent response. You can toggle `enable_thinking` and still get valid output.

Fallbacks
- If VRAM is insufficient, temporarily swap to a smaller Qwen3 variant for dev, then optimize later.

---

## 6) TTS Sanity Path

Choose one:
- Edge‑TTS: synthesize to `response.wav` using the snippet (7.1).
- Piper: install the engine and a voice model; synthesize to WAV via CLI or Python.

Done When
- `response.wav` exists, plays in your default player, and sounds correct.

Note
- For production, normalize audio and set a consistent sample rate (e.g., 44.1 kHz or 48 kHz) to match VTS settings.

---

## 7) Audio Routing to VTS

- Install a virtual audio device (e.g., VB‑Audio Virtual Cable) or enable loopback.
- In VTubeStudio, set the microphone device to the virtual cable.
- Confirm audio level meters move in VTS when you play `response.wav` to that device.

Done When
- VTS lip‑syncs to the WAV playback via the selected device.

Pitfalls
- Wrong input device selected in VTS or Windows privacy settings blocking mic access.

---

## 8) VTubeStudio API — Token & Auth

- Use the raw WebSocket example (6.1) or `pyvts` to request a token.
- Approve the popup in VTS; save token to `.vts_token.json`.
- Authenticate and trigger a test hotkey (e.g., Smile) that you configured in VTS.

Done When
- Auth response contains `authenticated: true` and the test hotkey visibly triggers in VTS.

Troubleshooting
- Ensure “Allow Plugins to Access API” is enabled and port matches (default 8001).

---

## 9) Memory Backend — Wire Up Stubs

- Keep `memory_retrieve` and `memory_write` as stubs initially.
- Return a static persona string (e.g., “Nova is friendly; user is Noah”) to unblock the pipeline.

Done When
- The orchestrator (later) composes prompts including the stubbed persona without errors.

Rationale
- Unblocks E2E chat while you decide between Letta and MemGPT.

---

## 10) Orchestrator Skeleton (E2E)

- Create `run_agent.py` based on section 8 in `agent.md`.
- Implement routing: if an image URL is present, call VLM; otherwise call LLM.
- After response, write a line to `response.wav` via chosen TTS, and trigger a simple VTS hotkey.

Done When
- Running `python run_agent.py` produces a spoken response and triggers a VTS expression on demand.

Validation
- Change input text to include an image URL and verify the VLM path is used.

---

## 11) Letta or MemGPT Integration

Pick one:
- Letta Cloud
  - Obtain API key; install `letta-client`.
  - Replace stubs with real `client.memory.search` and `client.memory.write` calls.
  - Store `LETTA_API_KEY` in `.env` and load at runtime.
- MemGPT (local)
  - Follow MemGPT README to run the memory service.
  - Implement a small client to read/write memory blocks and summaries.

Done When
- At the start of each turn, you can fetch relevant memories and persona; after the turn, you append summaries/facts successfully.

Notes
- Keep the working context short and targeted; Letta/MemGPT policies will manage FIFO history.

---

## 12) Safety & Moderation Pass (MVP)

- Add a pre‑generation and post‑generation filter:
  - Simple keyword/regex blocklist for profanity/NSFW.
  - Optional: lightweight classifier or a smaller moderation model.
- Strip any `<think>...</think>` content from user‑visible output if thinking mode is used.
- Add a hard cap on `max_new_tokens` and temperature bounds.

Done When
- Unsafe prompts are blocked or redirected, and no chain‑of‑thought is exposed in UI.

---

## 13) Latency & Quality Tuning

- Measure per‑stage latency (memory, VLM/LLM, TTS, VTS API).
- For casual chat, disable thinking mode; for complex reasoning, enable it selectively.
- Consider quantization if VRAM or latency is tight:
  - bitsandbytes 4‑bit (Windows support can be tricky); or use AWQ/GPTQ variants if available.
  - Alternatively, smaller model for chat; keep VLM as‑is.

Done When
- Text‑only turns complete in a target budget (e.g., <2–3s on your hardware) and image turns are acceptable for your use case.

---

## 14) Config, Secrets, and Logging

- Add `.env` for secrets (LETTA_API_KEY, voice, VTS URL/port) and a `config.yaml` with generation defaults and hotkey IDs.
- Implement structured logging with timestamps for request/response and errors.
- Add graceful error handling around WebSocket reconnect, TTS failures, and OOM.

Done When
- You can flip settings without code changes, and logs show each stage’s timing and outcomes.

---

## 15) Packaging & Run Scripts

- Create `scripts/` with PowerShell helpers:
  - `scripts/test_gpu.ps1` — CUDA check
  - `scripts/run_vts_auth.ps1` — token + auth flow
  - `scripts/run_agent.ps1` — env activation + run
- Optionally add `requirements.txt` freeze (`pip freeze > requirements.txt`).

Done When
- A fresh machine can follow scripts to reproduce your setup.

---

## 16) Optional: Game Loop MVP

- Choose a game with an API or stable emulator hooks.
- Implement `game_loop.py` with:
  - `get_game_state()` — poll state
  - `decide_action(state)` — rules + optional LLM planning
  - `send_action(action)` — API/automation (e.g., `pyautogui`)
- Hook VTS expressions to state (e.g., celebrate on win).

Done When
- The loop can detect a simple condition and perform the mapped action reliably.

Caution
- Respect EULAs and anti‑cheat; prefer official APIs.

---

## 17) QA Checklist

- Chat: multi‑turn text conversation retains persona across turns (memory write/read observed).
- Vision: image prompt produces a relevant description and does not crash.
- TTS/VTS: generated speech plays and VTS lip‑sync works consistently.
- Safety: blocked terms are filtered; thinking content never appears to users.
- Resilience: disconnect VTS during a run; app should warn and retry without crashing.

---

## 18) Roadmap (Post‑MVP)

- Streamed token output + incremental TTS for low latency.
- Event subscriptions from VTS (model loaded, tracking changes) to drive richer behavior.
- Persona editor UI; memory inspection tools; per‑user profiles.
- Tool calling for external APIs (calendar, web search) with guardrails.
- Metrics dashboard (latency, token usage, memory size) and crash reporting.

---

## File Map (Suggested)

- agent.md — Concept and reference guide.
- task.md — This execution plan.
- run_agent.py — Orchestrator (LLM/VLM/memory/TTS/VTS).
- game_loop.py — Optional game control loop.
- scripts/ — Helper PowerShell scripts.
- .env — Secrets (not committed).
- config.yaml — Runtime config.

---

## Ready‑To‑Go Next Step

- Implement steps 10–12 now: create `run_agent.py`, wire memory stubs, add safety filter, and validate E2E speaking response with VTS hotkey.

