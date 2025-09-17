# Neuro MVP Memory System (RAG)

This document specifies a practical, modern memory system for the agent that combines short‑term working memory with long‑term episodic + semantic memory using Retrieval‑Augmented Generation (RAG). It is designed to be local‑first, privacy‑aware, and modular, while supporting advanced techniques like multi‑query retrieval, re‑ranking, memory consolidation, graph memory, and importance‑driven reflection.

Goals:

- High‑quality context that improves answers and continuity.
- Separate, explicit partitions for persona, user profile, and general knowledge.
- Agentic RAG: retrieval steps that adapt to the task and iterate as needed.
- Local‑first by default; easy to switch to external vector DBs.
- Robust to long sessions via summarization, consolidation, and controlled forgetting.


## Architecture

Layers (top→bottom):

1) Working Memory (Short‑Term)
   - Rolling conversation window + rolling summary
   - Transient TODOs / plans / subgoals

2) Long‑Term Memory (Persistent)
   - Episodic memory: distilled moments from interactions with timestamps and context
   - Semantic memory: durable facts, preferences, skills, general knowledge
   - Knowledge Graph: triples and clusters linking entities/relations (GraphRAG‑inspired)

3) Reserved Partitions
   - Persona: agent’s role, voice, capabilities, constraints
   - User: profile, preferences, goals, style, constraints
   - General Facts/Knowledge: static reference info (e.g., project docs, FAQs)

4) Retrieval & Ranking
   - Hybrid search: dense embeddings + lexical (BM25/FTS)
   - Multi‑Query + HyDE query expansion; MMR dedup; cross‑encoder re‑rank
   - Recency and importance weighting

5) Consolidation & Forgetting
   - Periodic summarization of conversation into episodic memory
   - Promotion of stable patterns to semantic memory
   - Decay/spaced repetition; pinning to prevent forgetting

6) Safety & Privacy
   - PII detection and redaction rules
   - Secret‑pattern filters and opt‑out labels


## Data Model

Memory Item (normalized, stored in SQLite/JSON/Qdrant; unified across stores):

```
id:                string (ULID/UUID)
type:              enum [working, episodic, semantic, persona, user, general]
title:             string (short summary/title)
text:              string (full content)
embedding:         vector[float] (optional for persona/user/general; required for episodic/semantic)
importance:        int (0–10)  // LLM‑scored importance
recency_ts:        int (epoch ms)  // last seen/updated
created_ts:        int (epoch ms)
source:            string (e.g., chat:user, tool:xyz, file:path)
tags:              string[] (e.g., ["preference", "project:X"]) 
entities:          string[] (surface forms, optional)
triples:           [{subj, pred, obj}]  // optional; for graph queries
meta:              dict  // backend‑specific or app metadata
```

Graph Edge (optional; if GraphRAG is enabled):

```
id:            string
subj:          string
pred:          string
obj:           string
weight:        float  // derived from frequency + confidence
evidence_ids:  string[] // memory item ids
``` 


## Storage Backends

- Lite (default, local‑first):
  - SQLite for metadata + FTS5 for lexical search
  - FAISS (flat/IP or HNSW) for dense vectors (stored on disk)
  - Single file DB under `.data/memory.sqlite` and `.data/faiss.index`

- Standard (local server):
  - Qdrant (server or embedded) with `qdrant-client`
  - Hybrid: Qdrant vectors + SQLite FTS5 for lexicals

- Cloud (optional):
  - Pinecone/Weaviate/Typesense Hybrid, configured via env

Switching backends requires only config changes; the `MemoryStore` interface abstracts operations.


## Embeddings & Re‑ranking

- Dense embedding model (choose via config):
  - Local: `BAAI/bge-large-en-v1.5`, `intfloat/e5-large-v2`, `Alibaba-NLP/gte-large`.
  - Hosted: `text-embedding-3-small` or `-large`.

- Cross‑encoder re‑ranker (local, fast, high quality):
  - `jinaai/jina-reranker-v2-base-multilingual` or `BAAI/bge-reranker-large`

- Lexical:
  - SQLite FTS5 BM25 or optional SPLADE (advanced)


## Integration Points in This Repo

- `src/neuro_mvp/memory.py:1`: define a new `LocalRAGMemory` implementing the `MemoryClient` surface, or introduce a `MemoryRouter` that dispatches to `LettaMemory` or `LocalRAGMemory` based on config.
- `run_agent.py`: after each turn, call `memory.log_turn(...)` and `memory.consolidate_if_needed(...)`; before generation, call `memory.retrieve_context(...)` to build the prompt context.
- `config.yaml` and `.env`: add knobs for backend, model names, thresholds, and file paths.


## Read/Write Pipeline (Per Turn)

1) Ingest
   - Capture the user message, tool results, and assistant plan/outcome (if any).
   - Normalize (strip secrets, redact PII per rules).

2) Extraction & Scoring
   - Ask the LLM to propose candidate memory entries with fields: type, title, text, importance (0–10), tags, entities, triples.
   - Use simple heuristics to auto‑capture profile/preferences (already present in code), then merge with LLM output.

3) Dedup & Routing
   - For each candidate, compute embedding and check near‑duplicates (cosine > 0.90) in the destination partition.
   - Route to:
     - Persona: agent system traits (rare, mostly manual).
     - User: profile/preferences/goals.
     - General: durable facts/doc references.
     - Episodic: specific events and outcomes.
     - Semantic: promoted facts distilled from multiple episodes.

4) Commit
   - Write items to the vector store + SQLite row with metadata.
   - Update working memory: append to rolling transcript; refresh rolling summary.

5) Consolidation Triggers (asynchronous or periodic)
   - Importance budget: if sum(importance) over the last N turns > threshold, create episodic summary.
   - Novelty: if new info is not covered by existing semantic memory (similarity < τ), promote to semantic.
   - Time‑based: create session summary every K minutes of active conversation.


## Retrieval Pipeline (Before Generation)

1) Query Synthesis (Agentic)
   - Build multiple queries: literal user question, a HyDE‑style hypothetical answer, and a tool/goal‑oriented variant.
   - Include entities extracted from the last N turns and user profile.

2) Hybrid Retrieval
   - Run dense ANN (FAISS/Qdrant) and lexical (FTS5 BM25); union results.
   - Score = α·dense + β·lexical + γ·recency + δ·importance.
   - Apply MMR to penalize redundancy.

3) Re‑rank
   - Use cross‑encoder re‑ranker on the top 50–100 candidates → pick top K.

4) Context Assembly
   - Reserve token budget slices:
     - Persona slice (always include key persona items)
     - User slice (profile + preferences most relevant to query)
     - Working slice (rolling summary + last T turns)
     - Long‑term slice (episodic/semantic, re‑ranked)
     - General slice (project facts/docs)
   - Fit to model max context; drop least useful according to blended score.

5) Iterative Retrieval (Optional)
   - If the model indicates uncertainty or retrieval gaps, automatically perform a second retrieval pass with refined queries.


## Prompts (Core)

1) Extraction & Scoring Prompt

```
You are a memory extraction assistant. From the conversation turn below, propose JSON entries to store in long‑term memory. Prefer concise, factual, reusable items.

Return a JSON array of objects with fields:
- type: one of ["user", "persona", "semantic", "episodic", "general"]
- title: short summary
- text: full content
- importance: integer 0–10 (how crucial for future interactions?)
- tags: array of strings (optional)
- entities: array of strings (optional)
- triples: array of {subj, pred, obj} (optional)

Conversation turn:
<BEGIN>
{turn}
<END>
```

2) Working Summary Prompt (Hierarchical)

```
Summarize the last N turns into a concise working memory summary, preserving open tasks, decisions, and user preferences mentioned. Keep under {tokens} tokens.
```

3) Query Synthesis Prompt

```
Given the user request and working summary, produce:
- literal_query
- hypothetical_answer (HyDE)
- tool_goal_query (if tools/actions are implied)
```


## Consolidation & Forgetting

- Hierarchical Summarization: recursively compress transcripts into multi‑level summaries (session → episode → period), preserving links to evidence.
- Promotion Rules: if similar items recur across sessions and importance avg ≥ τ, merge into a single semantic fact.
- Decay: reduce score over time; use spaced repetition to resurface valuable but unseen items.
- Pinning: persona, critical user settings, and hard constraints are non‑decaying.


## Safety & Privacy

- PII Filters: redact credit cards, SSNs, auth tokens; skip writing if matches secret patterns.
- Opt‑Out Tags: any item with tag `no-store` or `sensitive` is stored only in ephemeral working memory unless user explicitly allows persistence.
- Right to Forget: implement `memory.delete(tag|id)` and `memory.clear(type=...)` commands.


## API Surface (Python)

High‑level interface used by the agent:

```
class MemoryService:
    def log_turn(self, user_text: str, assistant_text: str, tool_events: list[dict] = []) -> None: ...
    def retrieve_context(self, query: str, budget_tokens: int) -> dict: ...  # returns context pack
    def add(self, item: MemoryItem) -> str: ...
    def delete(self, id: str | None = None, tag: str | None = None, type: str | None = None) -> int: ...
    def consolidate_if_needed(self) -> None: ...
    def export(self, types: list[str]) -> list[MemoryItem]: ...
```

Context pack shape returned by `retrieve_context`:

```
{
  "persona": [MemoryItem, ...],
  "user": [MemoryItem, ...],
  "working": {"summary": str, "recent_turns": [str, ...]},
  "long_term": [MemoryItem, ...],
  "general": [MemoryItem, ...]
}
```

Injection into the model prompt happens in a deterministic order with clear section headers to aid grounding.


## Implementation Plan (Phased)

Phase 1 — Minimal, Local‑First

- Add `LocalRAGMemory` with SQLite + FAISS under `src/neuro_mvp/memory_local.py`.
- Extend `src/neuro_mvp/memory.py` to route to Letta or Local based on `MEMORY_PROVIDER`.
- Implement working memory (rolling N turns + rolling summary) persisted in SQLite.
- Implement extraction prompt + heuristic auto‑capture, dedup, and writes.
- Implement retrieval: dense + FTS5, MMR, cross‑encoder re‑rank, context assembly.

Phase 2 — Consolidation & Graph

- Periodic hierarchical summarization with evidence links.
- Promotion pipeline from episodic → semantic.
- Triple extraction; store edges; graph‑assisted queries (expand entities).

Phase 3 — Advanced Retrieval & Control

- Multi‑hop iterative retrieval; uncertainty‑driven second pass.
- Spaced repetition surfacing for rare but important facts.
- Full delete/export tooling and user commands.


## Config (.env / config.yaml)

Suggested new env vars:

- `MEMORY_PROVIDER` = `local` | `letta` | `qdrant` | `pinecone`
- `MEMORY_DB_PATH` = `.data/memory.sqlite`
- `MEMORY_FAISS_PATH` = `.data/faiss.index`
- `EMBEDDING_MODEL` = `BAAI/bge-large-en-v1.5`
- `RERANKER_MODEL` = `jinaai/jina-reranker-v2-base-multilingual`
- `MEMORY_TOP_K` = 24
- `MEMORY_WORKING_TURNS` = 12
- `MEMORY_IMPORTANCE_THRESHOLD` = 6
- `MEMORY_DEBUG` = `0|1`

YAML example (add to `config.yaml`):

```
memory:
  provider: local
  db_path: .data/memory.sqlite
  faiss_path: .data/faiss.index
  embedding_model: BAAI/bge-large-en-v1.5
  reranker_model: jinaai/jina-reranker-v2-base-multilingual
  top_k: 24
  working_turns: 12
  importance_threshold: 6
```


## Prompt Injection & Output Formatting

- Always include persona and user slices first.
- Mark memory items with `[source: … | importance: … | last_seen: …]` for transparency.
- Keep the final prompt below model’s max context with a strict budgeter that trims least‑useful items first.


## Newest Breakthroughs Incorporated

- Agentic RAG: iterative query synthesis and re‑retrieval based on model uncertainty.
- Graph‑assisted retrieval (GraphRAG): lightweight triple extraction + entity expansion.
- Cross‑encoder re‑ranking: strong accuracy gains over pure vector similarity.
- Importance‑driven reflection: LLM assigns importance; accumulation triggers consolidation.
- Recency‑aware hybrid scoring and MMR for diversity.
- Hierarchical, rolling summaries to stabilize context over long sessions.


## Security Considerations

- Secret patterns blacklist and entropy checks before writes.
- PII tagging and opt‑out storage; configurable retention windows.
- Export/delete APIs to enable “right to forget”.


## Validation & Metrics

- Track retrieval precision@k on held‑out Q&A snippets from recent chats.
- Log re‑ranker score distributions; alert on drift.
- Periodically sample outputs for grounding quality (does the answer cite retrieved items?).


## Next Steps in This Repo

- Create `src/neuro_mvp/memory_local.py` with `LocalRAGMemory` (SQLite+FAISS) and wire it into `MemoryClient`.
- Add config/env toggles and minimal installer for FAISS CPU.
- Implement prompts in `src/neuro_mvp/openai_compat.py` or wherever generation happens to inject the context pack.
- Provide CLI tools in `tools/` to inspect, export, and prune memory.


## Questions For You

1) Storage preference: stay fully local (SQLite+FAISS) or OK with Qdrant/Pinecone?
2) Privacy: should we never persist raw transcripts, only summaries, unless explicitly requested?
3) Multi‑user: do you foresee multiple distinct users or just one primary user profile?
4) Model constraints: do you want local embedding/reranker models, or use hosted APIs?
5) Token budgets: typical max context for your chat model(s)?
6) Retrieval strictness: favor precision (smaller K + heavy re‑rank) or recall (larger K)?
7) Persona control: do you want multiple personas selectable per session?
8) Deletion policy: add an easy command like “forget last session” or “forget X”? Any retention limits?
9) General knowledge: point to specific project folders/files to index by default?
10) OK to add minimal dependencies (sqlite-utils, faiss-cpu, qdrant-client, sentence-transformers)?


— End of spec —
