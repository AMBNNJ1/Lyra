Findings

High: Memory backend selection is ignored; MemoryClient always requires MEM0_API_KEY and uses Mem0, so the default Qdrant config and per-user labels won’t apply. memory.py (line 20), config.yaml (line 33), web_session.py (line 63)
High: Guest quota can be bypassed by omitting X-Guest-Id, and all unauthenticated users share a single guest-anon session/memory. server.py (line 99), server.py (line 130)
Medium: Streaming does a second LLM call and stores a different assistant than what was streamed; the prompt also duplicates the user message. This can desync UI vs history/memory. web_session.py (line 307), web_session.py (line 330), web_session.py (line 341)
Medium: mem0-service exposes read/write/delete memory endpoints with permissive CORS and no auth; if reachable externally, it is open to abuse. server.js (line 8), server.js (line 276)
Low: Streaming OpenAI-compatible requests have no timeout, risking hung workers on stalled upstreams. openai_compat.py (line 195)
Questions / Assumptions

Should the memory backend be Qdrant (per config) or hosted Mem0? This drives how MemoryClient should be wired. config.yaml (line 33)
Do you want guest mode to work without X-Guest-Id (server-generated cookie), or should the header be mandatory to enforce quotas? server.py (line 99)
Is mem0-service intended to be internal-only or exposed publicly? That affects auth/CORS strategy. server.js (line 8)
Plan

Unify chat and stream generation so the user message is always in the prompt, tool results are injected once, and the streamed output matches what is stored in history. web_session.py (line 230)
Implement memory backend switching (Mem0 vs Qdrant), and apply config-provided persona/user labels; update tests for each backend. memory.py (line 20)
Enforce guest isolation and quotas even without X-Guest-Id (issue a cookie or require the header), and add tests for bypass cases. server.py (line 99)
Secure mem0-service with auth and a CORS allowlist or bind it to localhost/private network. server.js (line 8)
Add streaming timeouts and consider session cleanup/TTL to prevent unbounded growth. openai_compat.py (line 195)