# Mem0 bridge for Lyra

This lightweight service wraps [Mem0](https://docs.mem0.ai) so the Python agent can talk to it over HTTP while the
memory graph persists inside the existing Qdrant instance.

## Setup

1. Install Node.js >= 18.
2. From the repo root: `cd mem0-service && npm install`.
3. Install a local embedding model with [Ollama](https://ollama.com/) (free, runs locally):
   ```powershell
   ollama pull all-minilm:latest
   ```
   You can pick another embedding model, but `all-minilm:latest` (384-dimensional) matches the default Qdrant dimension.
4. Copy `.env.example` to `.env` and set:
   - `QDRANT_URL` and `QDRANT_API_KEY` (if required)
   - `QDRANT_COLLECTION`, `QDRANT_DIM`, `QDRANT_DISTANCE` (must match your existing collection)
   - Optional: `MEM0_OLLAMA_URL`, `MEM0_EMBED_MODEL`
5. Run `npm run dev` (auto-reload) or `npm start` (production). The service listens on `http://127.0.0.1:4040`.
6. Ensure the Python agent has `MEM0_BASE_URL` pointing at the service.

### Environment variables

```
QDRANT_URL=...
QDRANT_API_KEY=...
QDRANT_COLLECTION=memory_items
QDRANT_DIM=384
QDRANT_DISTANCE=Cosine
MEM0_PORT=4040
MEM0_EMBED_PROVIDER=ollama
MEM0_EMBED_MODEL=all-minilm:latest
MEM0_OLLAMA_URL=http://127.0.0.1:11434
# Optional: MEM0_OPENAI_API_KEY for higher-tier summarisation
```

## Why a local embedder?

Mem0 defaults to OpenAI embeddings. Without an API key you’ll see `AuthenticationError: 401`. By configuring the
Ollama embedder we generate vectors locally at no cost, keep data private, and avoid rate limits. Just make sure Qdrant’s
vector dimension matches the embedding model you select.
