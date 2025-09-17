Here’s the fastest way to wire up Brave Search API in your app.

1) Get an API key

Create an account and subscribe to a plan (Free works for testing).

Generate a key in API Keys. You’ll send it in the X-Subscription-Token header. 
Brave

Key web-search endpoint:
GET https://api.search.brave.com/res/v1/web/search (others: news, images, video, local, summarizer, AI Grounding). 
Brave
+2
Brave
+2

Useful params: q, country, search_lang, ui_lang, count (≤20), offset (use 0..9 for pages), freshness, safesearch, result_filter. 
Brave

2) Minimal code you can drop in
Python (requests)
import os, requests

BRAVE_KEY = os.getenv("BRAVE_SUBSCRIPTION_TOKEN")

def brave_web_search(query, *, count=10, offset=0, lang="en", country="US"):
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_KEY,
    }
    params = {
        "q": query,
        "count": min(count, 20),
        "offset": offset,    # page index 0..9
        "search_lang": lang,
        "country": country,
        "safesearch": "moderate",
    }
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    # Normalize a compact list of results
    web = (data.get("web") or {}).get("results", [])
    return [
        {"title": it.get("title"), "url": it.get("url"), "snippet": it.get("description")}
        for it in web
    ]

if __name__ == "__main__":
    for item in brave_web_search("qdrant vector database"):
        print(f"- {item['title']}: {item['url']}")


Headers and endpoint per docs; count/offset pagination matches Brave behavior. 




3) Grounded Q&A (optional, great for agents)

Brave’s AI Grounding gives LLM-ready, source-cited answers via an OpenAI-compatible chat.completions endpoint:

from openai import OpenAI
import os

client = OpenAI(
  api_key=os.getenv("BRAVE_SUBSCRIPTION_TOKEN"),
  base_url="https://api.search.brave.com/res/v1",
)

resp = client.chat.completions.create(
  model="brave",
  messages=[{"role":"user","content":"What is Qdrant and how does it differ from Milvus? Cite sources."}],
  stream=False,
  # enable_research=True  # allow multiple searches if you want deeper digging
)
print(resp.choices[0].message.content)


Endpoint: POST /res/v1/chat/completions. Supports streaming, includes spend & search count metadata, and you can enable multi-search via enable_research. 
Brave

4) Practical tips (prod-ready)

Pagination: count ≤ 20 and offset is a page index (0..9). For 60 results, iterate offset=0..2. Results may slightly overlap. 
Brave

Rate limits: Inspect X-RateLimit-Limit headers to understand per-sec / monthly limits; cache popular queries to stay under quotas. 
Brave

Fresh content: Use freshness=pd|pw|pm|py|YYYY-MM-DDtoYYYY-MM-DD for recency filters. 
Brave

Local/POIs: For place-like queries, first hit web search, then call Local endpoints with returned locations[].id to expand POI details and AI descriptions. 
Brave

Plans & usage: There’s a Free tier; paid tiers add features and higher throughput. Recent updates added AI Grounding. Check current pricing/limits before scaling. 


5) Drop-in “search tool” for your agent

Return a compact, LLM-friendly schema:

def brave_search_tool(query):
    rows = brave_web_search(query, count=10)
    # Format as citations for your LLM or RAG step
    return {"query": query, "results": [
        {"title": r["title"], "url": r["url"], "snippet": r["snippet"]} for r in rows
    ]}


Use this as a tool in your agent to ground answers, or swap to the AI Grounding endpoint when you want one-shot, source-backed completions.

If you tell me your language/framework (you’ve been mostly Python, but if this needs to plug into your Next.js/Express stack or your local LLM agent), I’ll tailor an exact integration (middleware, caching, retries, and a tiny wrapper that normalizes web/news/image results).


Instructions for AI Agent:

You are an AI assistant with access to the Brave Search API. 
When a user asks about current events, facts, news, or information outside your training cutoff, 
you should call the Brave Search tool to retrieve results. 

Usage rules:
- Always send the query string to the Brave Search endpoint: https://api.search.brave.com/res/v1/web/search 
- Pass the API key in the X-Subscription-Token header.
- Default to count=10, offset=0, safesearch=moderate, search_lang=en, country=US unless user specifies otherwise.
- Parse the JSON response and extract:
   - title
   - url
   - description (snippet)
- Summarize the top 3–5 results into a concise, helpful answer. 
- Always cite sources with their URLs.
- If the user explicitly asks for raw results, return the JSON output directly.
- If results are empty, respond with: "No results found for your query."
- Do not hallucinate information — always ground answers in Brave Search output.

Example workflow:
1. User: "What’s happening with Solana today?"
2. You: Send Brave Search query with q="Solana news today".
3. Extract results.
4. Summarize into a natural language answer with 3 sources linked.
Web Search (Brave + Serper)

Overview
- Adds web search to ground answers with fresh sources.
- Provider priority: Brave (if `BRAVE_SUBSCRIPTION_TOKEN`) → Serper (if `SERPER_API_KEY`).
- Extracts page text for a few top results and packs short blocks for prompts.

Integration Points
- `src/neuro_mvp/web_search_tool.py`: provider selection, fetching, extraction, packing.
- `src/neuro_mvp/agent_loop.py`: registers a `search(query,k)` tool for the agent.
- `run_agent.py`: supports `/search your query` and injects packed results into chat context.

Setup
- Set one of in `.env`:
  - `BRAVE_SUBSCRIPTION_TOKEN=your-brave-key`
  - `SERPER_API_KEY=your-serper-key`
- Optional: `pip install trafilatura` for higher‑quality content extraction.

Usage
- Run: `python run_agent.py`
- At the prompt: `/search latest AI art trends`
- The agent prints a compact block (TITLE/URL/EXCERPT) and uses it next turn.

Returned Shapes
- Search tool: `{ "query": "...", "results": [{"title","url","snippet"}] }`
- Packed context (for prompts):

  TITLE: Example Title
  URL: https://example.com
  EXCERPT:
  First lines of the extracted content…

  ---

  TITLE: Another
  URL: https://example.org
  EXCERPT:
  …

Brave Search Quickstart
1) Get an API key
- Create an account and subscribe to a plan (Free works for testing).
- Generate a key in API Keys. Send it in `X-Subscription-Token`.

Endpoints
- Web search: GET `https://api.search.brave.com/res/v1/web/search`
- Others: news, images, video, local, summarizer, AI Grounding

Useful params
- `q`, `country`, `search_lang`, `ui_lang`, `count (≤20)`, `offset (0..9)`, `freshness`, `safesearch`, `result_filter`.

Minimal Python snippet
import os, requests

BRAVE_KEY = os.getenv("BRAVE_SUBSCRIPTION_TOKEN")

def brave_web_search(query, *, count=10, offset=0, lang="en", country="US"):
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_KEY,
    }
    params = {
        "q": query,
        "count": min(count, 20),
        "offset": offset,    # page index 0..9
        "search_lang": lang,
        "country": country,
        "safesearch": "moderate",
    }
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    web = (data.get("web") or {}).get("results", [])
    return [
        {"title": it.get("title"), "url": it.get("url"), "snippet": it.get("description")}
        for it in web
    ]

if __name__ == "__main__":
    for item in brave_web_search("qdrant vector database"):
        print(f"- {item['title']}: {item['url']}")

Grounded Q&A (optional)
- Brave AI Grounding via OpenAI‑compatible `POST /res/v1/chat/completions`.

from openai import OpenAI
import os

client = OpenAI(
  api_key=os.getenv("BRAVE_SUBSCRIPTION_TOKEN"),
  base_url="https://api.search.brave.com/res/v1",
)

resp = client.chat.completions.create(
  model="brave",
  messages=[{"role":"user","content":"What is Qdrant vs Milvus? Cite sources."}],
  stream=False,
  # enable_research=True  # allow multiple searches
)
print(resp.choices[0].message.content)

Tips
- Pagination: `count ≤ 20`, `offset` as page index (0..9). For ~60 results use offsets 0..2.
- Rate limits: read headers and cache popular queries.
- Freshness: `freshness=pd|pw|pm|py|YYYY-MM-DDtoYYYY-MM-DD` for recency.
- Local: for POIs, first web search then Local with `locations[].id`.

Agent Rules (Brave)
- Always send queries to the Brave endpoint with `X-Subscription-Token`.
- Defaults: `count=10`, `offset=0`, `safesearch=moderate`, `search_lang=en`, `country=US`.
- Extract `title`, `url`, `description` (snippet).
- Summarize top 3–5 with URLs as citations.
- If empty results: "No results found for your query."
- Do not hallucinate; ground answers in Brave output.
