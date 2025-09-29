from __future__ import annotations

import os
import asyncio
import re
from typing import List, Dict, Any

import httpx
try:
    # Optional; if unavailable we fall back to no-retry behavior
    from tenacity import retry, stop_after_attempt, wait_exponential  # type: ignore
except Exception:  # pragma: no cover - graceful fallback when tenacity not installed
    def retry(**kwargs):  # type: ignore
        def _wrap(fn):
            return fn
        return _wrap

    def stop_after_attempt(n: int):  # type: ignore
        return None

    def wait_exponential(**kwargs):  # type: ignore
        return None


def _serper_key() -> str | None:
    # Read at call time so .env can be loaded later
    return os.getenv("SERPER_API_KEY")


def _brave_token() -> str | None:
    # Read at call time so .env can be loaded later
    return os.getenv("BRAVE_SUBSCRIPTION_TOKEN")

USER_AGENT = "Mozilla/5.0 (compatible; AgentSearch/1.0; +https://example.com/bot)"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}


async def _fetch(session: httpx.AsyncClient, url: str, timeout: int = 15) -> str:
    r = await session.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _clean_text(html: str) -> str:
    # Try high-quality extraction if available
    try:
        import trafilatura  # type: ignore
        text = trafilatura.extract(html, include_comments=False, favor_recall=True) or ""
    except Exception:
        # Fallback: very naive HTML cleanup
        text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
async def _search_serper(query: str, num: int = 8) -> List[Dict[str, str]]:
    SERPER_API_KEY = _serper_key()
    if not SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY not set")
    async with httpx.AsyncClient(timeout=15) as session:
        try:
            r = await session.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": min(int(num or 8), 10)},
                headers={"X-API-KEY": SERPER_API_KEY, **HEADERS},
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:  # type: ignore
            resp = getattr(e, "response", None)
            code = getattr(resp, "status_code", None)
            detail = None
            try:
                if resp is not None:
                    js = resp.json()
                    detail = js.get("message") or js.get("error")
            except Exception:
                try:
                    detail = (resp.text or "")[:300] if resp is not None else None
                except Exception:
                    detail = None
            raise RuntimeError(f"Serper error {code}: {detail or str(e)}")
        except Exception as e:
            raise RuntimeError(f"Serper request failed: {e}")
    items = (data or {}).get("organic", [])[: int(num or 8)]
    return [
        {"title": it.get("title", ""), "url": it.get("link", ""), "snippet": it.get("snippet", "")}
        for it in items
    ]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
async def _search_brave(query: str, num: int = 8) -> List[Dict[str, str]]:
    BRAVE_SUBSCRIPTION_TOKEN = _brave_token()
    if not BRAVE_SUBSCRIPTION_TOKEN:
        raise RuntimeError("BRAVE_SUBSCRIPTION_TOKEN not set")
    params = {
        "q": query,
        "count": min(int(num or 8), 20),
        "offset": 0,
        "search_lang": "en",
        "country": "US",
        "safesearch": "moderate",
    }
    headers = {"X-Subscription-Token": BRAVE_SUBSCRIPTION_TOKEN, **HEADERS, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=15) as session:
        try:
            r = await session.get("https://api.search.brave.com/res/v1/web/search", params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:  # type: ignore
            resp = getattr(e, "response", None)
            code = getattr(resp, "status_code", None)
            detail = None
            try:
                if resp is not None:
                    js = resp.json()
                    detail = js.get("message") or js.get("error")
            except Exception:
                try:
                    detail = (resp.text or "")[:300] if resp is not None else None
                except Exception:
                    detail = None
            raise RuntimeError(f"Brave error {code}: {detail or str(e)}")
        except Exception as e:
            raise RuntimeError(f"Brave request failed: {e}")
    web = (data or {}).get("web") or {}
    results = web.get("results") or []
    items = results[: int(num or 8)]
    return [
        {"title": it.get("title", ""), "url": it.get("url", ""), "snippet": it.get("description", "")}
        for it in items
    ]


async def search_and_extract(query: str, num_results: int = 6, max_chars_per_page: int = 4000) -> Dict[str, Any]:
    # Provider preference: Brave -> Serper
    brave = _brave_token()
    serper = _serper_key()
    if brave:
        try:
            hits = await _search_brave(query, num_results)
        except Exception as e:
            # Fallback to Serper if configured
            if serper:
                hits = await _search_serper(query, num_results)
            else:
                raise
    elif serper:
        hits = await _search_serper(query, num_results)
    else:
        raise RuntimeError("No web search provider configured (set BRAVE_SUBSCRIPTION_TOKEN or SERPER_API_KEY)")
    urls = [h.get("url") for h in hits if h.get("url")]
    contents: Dict[str, str] = {}
    async with httpx.AsyncClient(timeout=20) as session:
        tasks = [asyncio.create_task(_fetch(session, u)) for u in urls]
        htmls = await asyncio.gather(*tasks, return_exceptions=True)
    for u, html in zip(urls, htmls):
        if isinstance(html, Exception):
            contents[u] = ""
            continue
        txt = _clean_text(html)[: int(max_chars_per_page or 4000)]
        contents[u] = txt
    results: List[Dict[str, str]] = []
    for h in hits:
        results.append(
            {
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "snippet": h.get("snippet", ""),
                "content": contents.get(h.get("url", ""), ""),
            }
        )
    return {"query": query, "results": results}


def pack_for_context(payload: Dict[str, Any], max_pages: int = 3, per_page_chars: int = 1200) -> str:
    blocks: List[str] = []
    for r in (payload.get("results") or [])[: int(max_pages or 3)]:
        body = (r.get("content") or r.get("snippet") or "")[: int(per_page_chars or 1200)]
        title = r.get("title", "")
        url = r.get("url", "")
        blocks.append(f"TITLE: {title}\nURL: {url}\nEXCERPT:\n{body}")
    return "\n\n---\n\n".join(blocks)


def web_search_tool(query: str, k: int = 6) -> Dict[str, Any]:
    """Synchronous convenience wrapper returning structured results.

    Returns the same payload shape as `search_and_extract`.
    """
    return asyncio.run(search_and_extract(query, num_results=int(k or 6)))
