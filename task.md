# Lyra Roadmap

This checklist keeps the web companion focused and shippable. Tackle items in order; each has a clear ?done when? so you know when to move on.

## 1. Core Experience

- **Set up infrastructure**
  - Provision Qdrant (cloud or self-hosted) and record `QDRANT_URL`, `QDRANT_API_KEY`.
  - Deploy or run the Mem0 Node service locally on `http://127.0.0.1:4040`.
  - Configure Clerk application (publishable key + issuer/JWKS URL).
- **Backend**
  - Ensure `/api/chat`, `/api/chat/stream`, `/api/tts`, `/api/auth/config` respond locally.
  - Confirm guest quota works (five messages) and Clerk tokens unlock unlimited chat.
- **Frontend**
  - Chat page shows avatar hero video, streaming transcript, emotion cue, and sign-in modal.
  - Voice page captures mic input, sends chat requests, and plays Kokoro audio.

Done when: chatting and talking works end-to-end with memories persisting in Qdrant.

## 2. Memory Quality

- Seed persona and baseline user profile via `tools/init_memory_db.py`.
- Tune `AutoMemoryConfig` thresholds so important facts stick.
- Review the Mem0 dashboard to validate labels (`profile`, `preferences`, `facts`, `goals`, `general`).
- Add manual edit/delete flows in the dashboard or CLI if needed.

Done when: Lyra recalls preferences across sessions and stored items look clean.

## 3. Search & Tooling (Optional)

- Set `BRAVE_SUBSCRIPTION_TOKEN` or `SERPER_API_KEY`.
- Expose a ?Search the web? action in the chat UI that renders `pack_for_context` results.
- Teach the agent how to cite URLs in replies.

Done when: a query like ?What happened with Qdrant this week?? returns grounded answers with source links.

## 4. Deployment

- Host the Flask service (e.g., Render, Fly.io, Railway) and verify HTTPS.
- Deploy the static site to Vercel using `vercel.json` and set `BACKEND_URL` plus Clerk env vars.
- Configure production Mem0 endpoint and Qdrant credentials.

Done when: the public URL loads the chat page, sign-in works, and the backend talks to Qdrant.

## 5. Quality & Monitoring

- Run `python -m pytest` in CI (GitHub Actions or other) on every push.
- Add logging for memory writes, search usage, and Clerk failures.
- Set up health checks for Mem0 and Qdrant connectivity.

Done when: you can spot/auth troubleshoot issues quickly and the test suite guards regressions.

## 6. Enhancements (Future)

- Richer avatar reactions mapped to emotion intensity.
- Streaming Kokoro playback for lower latency.
- Multi-user dashboards with memory export/import.
- Analytics around memory growth and retrieval hit rates.

Keep the focus on delivering a delightful, privacy-aware AI companion: great conversations, reliable recall, and a welcoming UI.
