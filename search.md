# Web Search Integrations

Lyra can ground responses with live web data. The backend includes helpers for Brave Search and Serper; you only need to drop in API keys and call the tool when a conversation needs fresh information.

## Providers

| Provider | Env Vars | Notes |
|----------|----------|-------|
| Brave    | `BRAVE_SUBSCRIPTION_TOKEN` | Higher quality, includes OpenAI-compatible AI Grounding endpoint. |
| Serper   | `SERPER_API_KEY`           | Google SERP wrapper used as a fallback when Brave is unavailable. |

Set the keys in `.env` and restart the Flask server. If neither is configured the search tool raises an explicit error so you can hide the button in the UI.

## Core Module

`src/neuro_mvp/web_search_tool.py` exports:

- `_search_brave(query, num)` ? async Brave API wrapper with retries.
- `_search_serper(query, num)` ? async Serper wrapper.
- `_clean_text(html)` ? strips scripts/styles and returns readable text (uses `trafilatura` if installed).
- `search_and_extract(query, num_results)` ? orchestrates provider selection, fetches web pages concurrently, and attaches clean excerpts.
- `pack_for_context(payload)` ? formats search results into `TITLE/URL/EXCERPT` blocks for prompts or UI display.
- `web_search_tool(query, k)` ? synchronous helper for agent tool invocations.

## Usage from the Agent

```python
from neuro_mvp.web_search_tool import web_search_tool, pack_for_context

def handle_search(query: str) -> str:
    payload = web_search_tool(query, k=6)
    return pack_for_context(payload, max_pages=3, per_page_chars=1200)
```

Include the result string in the LLM prompt or stream it back to the chat UI. Each block already contains the URL so you can surface clickable citations.

## Voice & Chat UI Hooks

- Chat page: add a ?Search the web? button that POSTs to a custom endpoint calling `web_search_tool` and inserts the formatted block into the transcript.
- Voice page: when a user asks for news, run the search before synthesizing the spoken reply so Lyra can cite sources.

## Tips

- Respect rate limits: cache popular queries or debounce repeated requests.
- `max_chars_per_page` controls how much text you send into the LLM context; keep it small for faster responses.
- If you want summarised answers instead of raw snippets, call Brave?s `chat/completions` endpoint with `model="brave"`.

With the keys in place, Lyra can blend remembered facts from Qdrant with the latest information pulled from the web.
