from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Iterator

import os
import requests
import json


def _build_headers(api_key: Optional[str]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}{path}"


@dataclass
class ChatLLMConfig:
    base_url: str
    model: str
    max_new_tokens: int = 128
    temperature: float = 0.7
    api_key: Optional[str] = None


class OpenAIChatLLM:
    def __init__(self, cfg: ChatLLMConfig):
        self.cfg = cfg
        self.enabled = True

    @staticmethod
    def _normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return a list that alternates user/assistant for LM Studio-style templates.

        - Concatenate all system messages and prepend to the first user message.
        - Drop roles other than user/assistant; merge consecutive same-role items.
        - Ensure the conversation starts with a user message; if not, create one.
        """
        sys_parts: List[str] = []
        for m in messages or []:
            role = m.get("role", "")
            if role == "system":
                content = m.get("content", "")
                if isinstance(content, list):
                    # Extract text parts
                    content = "\n".join([c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"])  # type: ignore
                if isinstance(content, str) and content.strip():
                    sys_parts.append(content.strip())

        result: List[Dict[str, Any]] = []
        def _append(role: str, content: str) -> None:
            if not content:
                return
            if result and result[-1]["role"] == role:
                # merge
                prev = result[-1]["content"] or ""
                result[-1]["content"] = (prev + "\n\n" + content).strip()
            else:
                result.append({"role": role, "content": content})

        # First convert all non-system messages
        for m in messages or []:
            role = m.get("role", "")
            if role not in {"user", "assistant"}:
                continue
            content = m.get("content", "")
            if isinstance(content, list):
                content = "\n".join([c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"])  # type: ignore
            if isinstance(content, str) and content.strip():
                _append(role, content.strip())

        # If no user message at all, synthesize one from system text
        has_user = any(m.get("role") == "user" for m in result)
        sys_text = "\n".join(sys_parts).strip()
        if not has_user:
            if sys_text:
                result = [{"role": "user", "content": sys_text}] + result
            else:
                result = [{"role": "user", "content": "You are a helpful assistant."}] + result
        else:
            # Prepend system text to the first user message
            if sys_text:
                for m in result:
                    if m.get("role") == "user":
                        m["content"] = (sys_text + "\n\n" + str(m.get("content") or "")).strip()
                        break

        # Ensure we start with a user and alternate; merge if duplicate roles remain
        if result and result[0]["role"] != "user":
            lead = "You are a helpful assistant."
            if sys_text:
                lead = sys_text
            result.insert(0, {"role": "user", "content": lead})

        # Final pass to strictly alternate by merging duplicates
        final: List[Dict[str, Any]] = []
        for m in result:
            if not final:
                final.append(m)
                continue
            if final[-1]["role"] == m["role"]:
                final[-1]["content"] = (str(final[-1]["content"]) + "\n\n" + str(m["content"])).strip()
            else:
                final.append(m)
        return final

    def generate(self, system: str, user_text: str) -> str:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        return self.generate_from_messages(messages)

    def generate_from_messages(self, messages: List[Dict[str, Any]]) -> str:
        # Normalize to user/assistant alternating for LM Studio prompt templates
        messages = self._normalize_messages(messages)
        # Primary: Chat Completions
        payload_chat = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "stream": False,
        }
        if int(self.cfg.max_new_tokens) >= 0:
            payload_chat["max_tokens"] = int(self.cfg.max_new_tokens)
        url_chat = _endpoint(self.cfg.base_url, "/chat/completions")
        try:
            r = requests.post(url_chat, headers=_build_headers(self.cfg.api_key), json=payload_chat, timeout=120)
            if r.status_code == 404:
                raise requests.HTTPError("404", response=r)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.HTTPError as e:
            # Fallback: some local servers only expose /v1/completions
            if getattr(e, "response", None) is None or e.response.status_code != 404:
                raise
            # Convert chat to a single prompt
            parts: List[str] = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                if isinstance(content, list):
                    # extract text parts
                    content = "\n".join([c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"])  # type: ignore
                parts.append(f"{role}: {content}")
            prompt = "\n\n".join(parts)
            payload_cmp = {
                "model": self.cfg.model,
                "prompt": prompt,
                "temperature": self.cfg.temperature,
                "stream": False,
            }
            if int(self.cfg.max_new_tokens) >= 0:
                payload_cmp["max_tokens"] = int(self.cfg.max_new_tokens)
            url_cmp = _endpoint(self.cfg.base_url, "/completions")
            r2 = requests.post(url_cmp, headers=_build_headers(self.cfg.api_key), json=payload_cmp, timeout=120)
            r2.raise_for_status()
            data2 = r2.json()
            # Some servers return choices[].text
            text = data2.get("choices", [{}])[0].get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            # Or choices[].message.content if they proxy chat
            msg = data2.get("choices", [{}])[0].get("message", {}).get("content")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
            # Fallback: return whole JSON as string
            return str(data2)

    def stream_from_messages(self, messages: List[Dict[str, Any]]) -> Iterator[str]:
        """Yield partial text deltas using OpenAI-style streaming via SSE.

        Falls back to a single full completion if the server does not support
        streaming chat completions.
        """
        messages = self._normalize_messages(messages)
        payload_chat = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "stream": True,
        }
        if int(self.cfg.max_new_tokens) >= 0:
            payload_chat["max_tokens"] = int(self.cfg.max_new_tokens)
        url_chat = _endpoint(self.cfg.base_url, "/chat/completions")
        try:
            with requests.post(url_chat, headers=_build_headers(self.cfg.api_key), json=payload_chat, stream=True) as r:
                if r.status_code == 404:
                    # Fallback: no streaming chat; yield once with full text
                    text = self.generate_from_messages(messages)
                    if text:
                        yield text
                    return
                r.raise_for_status()
                buffer = ""
                for raw in r.iter_lines(decode_unicode=False):
                    if raw is None:
                        continue
                    if not raw:
                        continue
                    try:
                        line = raw.decode('utf-8')
                    except UnicodeDecodeError:
                        line = raw.decode('utf-8', errors='replace')
                    line = line.strip()
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece
        except requests.HTTPError:
            # As a last resort, emit a single non-streaming response
            text = self.generate_from_messages(messages)
            if text:
                yield text


@dataclass
class ChatVLMConfig:
    base_url: str
    model: str
    max_new_tokens: int = 128
    temperature: float = 0.7
    api_key: Optional[str] = None


class OpenAIChatVLM:
    def __init__(self, cfg: ChatVLMConfig):
        self.cfg = cfg
        self.enabled = True

    def describe(self, image_url: str, prompt: str) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": int(self.cfg.max_new_tokens),
            "stream": False,
        }
        url = _endpoint(self.cfg.base_url, "/chat/completions")
        r = requests.post(url, headers=_build_headers(self.cfg.api_key), json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
