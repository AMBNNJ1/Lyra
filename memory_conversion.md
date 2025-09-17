# Memory Conversion (Short-Term → Long-Term)

This document describes how conversational short-term memory should be converted into long-term memory in this repo, aligning with the principles from the attached paper on Short-Term vs Long-Term memory in conversational AI. It fits the existing code paths in `src/neuro_mvp/memory.py`, `src/neuro_mvp/memory_local.py`, `src/neuro_mvp/memory_qdrant.py`, `src/neuro_mvp/memory_auto.py`, and the CLI/scripts under `tools/` and `scripts/`.

## Definitions (This Repo)

- Short-Term (ST):
  - Rolling window of recent turns plus the rolling working summary stored in SQLite (`working_summary` table for local; `working_summary` label for Qdrant).
  - Ephemeral state used to ground the next reply. Not all ST content should persist.
- Long-Term (LT):
  - Persistent items in `memory_items` with types/labels: `episodic`, `semantic` (facts), `profile`, `preferences`, `goals`, `persona`, and `general`.
  - Retrieved via hybrid search (lexical + optional embeddings) and re-ranked, then injected into prompts.

## Conversion Goals

- Preserve durable, reusable knowledge while keeping context small and relevant.
- Promote stable patterns (e.g., user preferences, goals) from ST → LT.
- Store episodic highlights as compact summaries, not raw transcripts.
- Avoid duplication; decay or compress low-utility items over time.

## Principles Applied

- Capacity is limited; ST holds only what’s needed for immediate grounding. LT stores compact, high-utility items.
- Conversion is gated by importance, stability (recurrence), and novelty (not already covered by an LT item).
- Consolidation is periodic and event-driven, not constant. It merges duplicates, promotes stable facts, and decays stale ones.

## Conversion Stages

1) Micro-capture per turn (already in repo)
   - Source: last user+assistant turn + current working summary line.
   - Method: `MemoryAutoUpdater` asks the LLM to propose concise JSON entries, plus heuristic regex autocapture for profile/preferences.
   - Gate: only store if `importance >= threshold` (default 6) and not `persona` unless manual.

2) Deduplicate and route
   - Use lexical similarity + optional vector similarity (if embeddings enabled) to detect near-duplicates (`dedup_lexical_threshold`, `dedup_vector_threshold`).
   - Route by type → label mapping:
     - user → `profile` or `preferences`
     - goals → `goals`
     - general → `general` (optional from auto, default off)
     - else → `facts` (semantic)

3) Promotion and consolidation (batch/periodic)
   - Merge near-duplicates; increment importance of merged items and keep the most informative phrasing.
   - Promote patterns: if similar statements appear K times across sessions, synthesize a single semantic fact (e.g., from multiple episodes → one `facts` line).
   - Decay: gradually lower importance for older items unless they’re pinned by recurrence or high base importance.

4) Retrieval and feedback
   - At query time, fetch relevant persona, user facts, working summary, and top LT items.
   - If retrieval repeatedly surfaces the same item, consider pinning or increasing its base importance.

## What’s Already Implemented Here

- ST working summary storage and episodic snippetting
  - Local: `working_summary` table; Qdrant: `working_summary` label.
  - `MemoryClient.log_interaction()` updates working summary and appends a compact episodic line.
- Auto extraction per turn
  - `src/neuro_mvp/memory_auto.py` generates candidate memory entries via LLM; regex autocapture for name, pronouns, likes, location, and “my favorite X is Y”.
- Dedup and importance
  - Local SQLite path includes lexical + optional embedding dedup; configurable thresholds in `LocalMemoryConfig`.
- Nightly consolidation & decay
  - `LocalRAGMemory.consolidate()` merges duplicates and decays old items.
  - Ready-to-use scripts: `scripts/run_memory_consolidate.ps1` and `scripts/schedule_memory_consolidation.ps1`.

## Recommended Enhancements (Targeted to This Repo)

- Promotion rules (episodic → semantic):
  - When K similar episodic lines appear (e.g., K=3) across sessions, synthesize a single `facts` record and mark the older episodic items as consolidated (keep last for traceability).
  - If an item is referenced in retrieval > N times over M days, bump its importance.
- Stability detection:
  - Track mention frequency windows per normalized key (e.g., `favorite food`, `timezone`, `workspace path`).
  - Use existing lexical + vector sim to group mentions; promote when both frequency and importance gates pass.
- Safer general knowledge capture:
  - Keep `general` off for auto-capture; rely on explicit `index_files()` and tools-initiated adds.
- PII and secrets hygiene:
  - Redact obvious secrets before writes; tag potential identifiers to allow easy deletion.

## Config Knobs (Proposed)

- `MEMORY_PROMOTE_MIN_MENTIONS` (default: 3): minimum recurring mentions to promote to `facts`.
- `MEMORY_PROMOTE_MIN_IMPORTANCE` (default: 6): average importance threshold to allow promotion.
- `MEMORY_SUMMARY_EVERY_N_TURNS` (default: 10): force a compact episodic summary after N turns.
- `MEMORY_MAX_WORKING_BULLETS` (default: from `working_turns`): hard cap of working bullets.

## Implementation Plan (Repo-Fit)

1) Add promotion gates to consolidate (local backend)
   - File: `src/neuro_mvp/memory_local.py`
   - Extend `consolidate()` to:
     - Group items by label ∈ {`episode`, `facts`, `preferences`, `profile`} and cluster by lexical/vector sim.
     - For clusters of size ≥ `MEMORY_PROMOTE_MIN_MENTIONS`, synthesize one semantic `facts` text (e.g., “User prefers X for Y”), set importance to max(cluster)+1, insert/update via `_upsert_item()`.
     - Mark merged episodic items as consolidated (e.g., `active=0`) except the newest; keep provenance in `meta`.
     - Preserve global persona; never auto-change it.

2) Wire promotion config
   - File: `src/neuro_mvp/memory.py`
   - Read env vars for promotion thresholds and pass into `LocalMemoryConfig` (add fields if needed).
   - Surface a `mem.consolidate()` call site:
     - Batch: continue nightly via `scripts/schedule_memory_consolidation.ps1`.
     - Optional: add a lightweight “every N turns” hook in `run_agent.py` (increment a counter and call `.consolidate()` when `N` is reached).

3) Improve auto extractor payload
   - File: `src/neuro_mvp/memory_auto.py`
   - Include `source` and `tags` in writes (e.g., `source=chat:turn`, tags from LLM output).
   - Keep `allow_general_from_auto=False` by default; reserve `general` for `index_files()` and tool-driven adds.

4) CLI support for promotion-only pass (optional)
   - File: `tools/memory_cli.py`
   - Add subcommand `promote` that calls `mem.consolidate()` but prints promotion-specific stats.

5) Metrics and sanity checks
   - Count duplicates merged, facts promoted, and items decayed per run; log to console.
   - Add `tools/memory_dashboard.py` views for “recent promotions” and “top facts by importance” (optional enhancement).

6) Config and docs
   - Update `.env.example` to show promotion knobs and comments.
   - Cross-link this document from `memory.md`.

## Safe Defaults

- Keep auto-capture strict (`importance >= 6`).
- Do not auto-write `persona` or `general` from LLM extraction.
- Dedup aggressively; prefer one compact `facts` item over many similar episodic lines.
- Summarize, don’t store raw transcripts, unless explicitly needed for debugging.

## KPIs to Watch

- Retrieval precision@k on recent chats with and without promotion enabled.
- Proportion of answers citing promoted facts vs. raw episodic memories.
- Consolidation stats over time: merged, promoted, decayed.

## Usage Notes (Today)

- Per turn, memory extraction runs automatically when the chat LLM is enabled.
- Consolidation can be run manually:
  - `python tools/memory_cli.py consolidate`
- Nightly schedule on Windows (PowerShell, Admin may be required):
  - `scripts/schedule_memory_consolidation.ps1 -Time 02:30 -TaskName NeuroMemoryConsolidate`

