# Lyra Conversational Agent

Lyra is a web-first companion that chats in real time, remembers what you share, and presents a friendly AI avatar. The experience is delivered through two pages:

- **Chat** ? text interface with a looping hero video of Lyra, live memory cues, and Clerk authentication gates.
- **Voice** ? push-to-talk mode that records speech, streams replies, and plays back synthesized audio.

Behind the scenes Lyra combines a Flask API, the Mem0 memory service, and optional web search tools so conversations stay grounded and personal.

## Highlights

- **Avatar-first UI** ? static hero image/video and accessible layout served from `/web/index.html`.
- **Secure auth with Clerk** ? Clerk JS handles sign in while the Flask backend verifies tokens server-side.
- **Persistent memory** ? Mem0 stores every fact and reflection and exposes it back to the agent.
- **Voice conversations** ? `/voice` reuses the same backend for chat plus Kokoro TTS and in-browser speech recognition.
- **Search & tools** ? Brave/Serper search wrappers (optional) return citations for the agent.
- **Tested core** ? pytest suite covers emotion heuristics, Clerk verification, memory helpers, auto memory, web utilities, and key API flows.

## Architecture Overview

```
Browser (chat + voice)          Clerk              Mem0 service
        |                        |                       |
        | 1. sign in             |<--------------------->|
        |----------------------->|                       |
        |                        |                       |
        | 2. chat/voice fetch    v                       |
        |--------------------> Flask API <-------------->| 3. memory sync
        |                        |                       |
        |<------------------ streaming responses + TTS audio ---|
```

- `web/server.py` exposes REST/SSE endpoints for chat, memory polling, TTS, and static assets.
- `mem0-service/` (Node) provides the memory bridge (`MEM0_BASE_URL`).
- `src/neuro_mvp` contains the agent runtime (memory client, auto updater, emotion engine, web search tooling).

## Repository Map

```
??? web/                # Static frontend (chat, voice, lyra demo, assets)
??? src/neuro_mvp/      # Python backend logic (memory, emotion, tools, auth)
??? tools/              # Diagnostics (memory dashboard, CLI)
??? scripts/            # PowerShell helpers for setup and deployment
??? mem0-service/       # Node.js memory bridge service
??? tests/              # pytest suite exercising core modules and APIs
??? README.md           # You are here
```

## Quick Start

### 1. Prerequisites

- Python 3.10+
- Node.js 18+
- Clerk account with a publishable key and server-side issuer/JWKS URL

### 2. Install Python dependencies

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Boot the Mem0 service

```powershell
cd mem0-service
npm install
copy .env.example .env   # configure as needed
npm run dev
```

Mem0 listens on `http://127.0.0.1:4040` by default. Point `MEM0_BASE_URL` to it.

### 4. Configure environment

Copy `.env.example` to `.env` and fill the following keys:

```
CLERK_PUBLISHABLE_KEY=
CLERK_ISSUER=
CLERK_JWKS_URL=
BRAVE_SUBSCRIPTION_TOKEN=   # optional search
SERPER_API_KEY=             # optional search fallback
MEM0_BASE_URL=http://127.0.0.1:4040
```

Tune `config.yaml` for model selection, memory thresholds, and Kokoro TTS voice.

### 5. Run the Flask backend

```powershell
python web/server.py
```

The API serves chat at `http://localhost:7860/`, the landing page at `/landing`, and the voice UI at `/voice`.

### 6. (Optional) Develop with Vercel

The static site can be published via Vercel. Ensure `vercel.json` points to `web/` as the output, set `BACKEND_URL` to your Flask deployment, and run `vercel --prod`.

## Testing

Automated tests cover authentication flow, memory utilities, auto-memory extraction, emotion heuristics, and HTML helpers.

```powershell
python -m pytest
```

## Additional Documentation

- [`agent.md`](agent.md) ? conversational flow, Clerk gating, and streaming behaviour.
- [`memory.md`](memory.md) ? how Mem0 structures Lyra?s memories.
- [`search.md`](search.md) ? Brave/Serper integration patterns.
- [`emotion.md`](emotion.md) ? OCC-inspired affect system powering the avatar.
- [`task.md`](task.md) ? development roadmap for future iterations.

## Deployment Checklist

1. Configure Mem0 service environment variables.
2. Configure Clerk keys in both the backend (`.env`) and frontend (`web/index.html` fetches `/api/auth/config`).
3. Host the Flask API (Render, Fly.io, self-managed) and expose HTTPS for the web client.
4. Deploy the static site to Vercel (or another CDN) pointing `BACKEND_URL` to the API host.
5. Verify chat, voice, and memory persistence in production.

Lyra is designed to be privacy-respectful and transparent?memories are stored securely, Clerk protects user interactions, and every response can cite where the information came from.
