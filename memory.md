# Lyra Memory Architecture

Lyra stores everything you share in Qdrant through the Mem0 bridge. This document explains how memories are structured, how they flow between services, and which knobs you can tweak.

## Components

- **Mem0 service** (`mem0-service/`): Node.js API that listens on `MEM0_BASE_URL` (default `http://127.0.0.1:4040`). It normalizes reads/writes and batches calls to Qdrant.
- **Qdrant**: vector database that holds long-term memories, indexed by user ID plus semantic tags.
- **`MemoryClient`** (`src/neuro_mvp/memory.py`): Python facade used by the Flask app to fetch context, log interactions, and execute tools.
- **`MemoryAutoUpdater`** (`src/neuro_mvp/memory_auto.py`): asks an LLM to summarize each turn into durable facts/goals.

## Memory Flow

1. Browser sends a chat/voice message.
2. Flask calls `MemoryClient.retrieve_context` to assemble persona, user profile, working summary, and long-term facts for the prompt.
3. After generating a reply, `MemoryClient.log_interaction` writes the exchange and `MemoryAutoUpdater.process_turn` extracts new memories (preferences, goals, general notes).
4. Mem0 pushes inserts/updates into Qdrant. The next turn reads them back through the same service.

## Collections & Labels

Memories are partitioned by label so prompts stay focused:

| Label         | Description                                  |
|---------------|----------------------------------------------|
| `persona`     | Who Lyra is (voice, constraints, character)   |
| `profile`     | Stable user facts (name, pronouns, location)  |
| `preferences` | Likes/dislikes, routines, favorite things     |
| `facts`       | Semantic knowledge or reminders               |
| `goals`       | Short- or long-term objectives                |
| `general`     | Documentation snippets or project references  |

`MemoryClient.retrieve_context` returns a pack with the following shape:

```
{
  "persona": [...],
  "user": [...],
  "working": {"summary": str, "recent_turns": [str, ...]},
  "long_term": [...],
  "general": [...]
}
```

Each block contains `{label, value}` pairs drawn from Qdrant vectors. Persona and user data are always included first to anchor the conversation.

## Configuration

### Environment

Set the following keys in `.env`:

```
MEM0_BASE_URL=http://127.0.0.1:4040
QDRANT_URL=https://<cluster>.cloud.qdrant.io:6333
QDRANT_API_KEY=<secret>
MEMORY_PROVIDER=qdrant
MEMORY_USER_LABEL=User is Noah.
```

Optional tuning:

```
MEMORY_TOP_K=24
MEMORY_BUDGET_TOKENS=1024
MEMORY_WORKING_TURNS=12
MEMORY_DEBUG=0|1
```

### `config.yaml`

```
memory:
  provider: qdrant
  auto:
    enable: true
    importance_threshold: 6
    max_items: 4
  persona: "Lyra is a kind AI companion who remembers details." 
  user_label: "User is Noah."
```

### Auto Memory

`MemoryAutoUpdater` prompt can be tuned via `AutoMemoryConfig`:

- `importance_threshold`: minimum 0?10 score required for storage.
- `max_items`: guardrail against memory spam.
- `allow_general_from_auto`: false by default; set true to let the LLM store documentation snippets automatically.

## Working with Memories

- **Inspect** ? `python tools/memory_dashboard.py` launches a local dashboard (default `http://localhost:8765`) showing persona, user, long-term, and general sections.
- **CLI** ? `python tools/memory_cli.py --help` for quick search/add/delete operations.
- **Programmatic** ? use `MemoryClient.execute_tool('memory_search', {...})` to expose a tool inside the agent.

## Best Practices

- Seed persona and user profile using `tools/init_memory_db.py` before the first run.
- Keep the importance threshold around 5?7 so only meaningful facts stick.
- Periodically archive or delete `general` memories if you index large docs.
- When migrating environments, export via `MemoryClient.export_json` and restore using Mem0?s HTTP endpoints.

Lyra?s recall quality depends on the completeness of persona/user data and the ongoing auto memory extraction. If the agent forgets something important, raise the importance score manually or pin the fact through the dashboard.
