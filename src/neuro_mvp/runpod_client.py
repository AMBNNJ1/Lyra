"""RunPod Serverless clients for LLM and TTS inference.

This module provides clients that call RunPod Serverless endpoints:
- RunPodLLMClient: OpenAI-compatible chat completions via vLLM
- RunPodTTSClient: Kokoro TTS via custom endpoint
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import requests


# ---------------------------------------------------------------------------
# LLM Client (vLLM on RunPod)
# ---------------------------------------------------------------------------


@dataclass
class RunPodLLMConfig:
    """Configuration for RunPod LLM endpoint."""

    endpoint_id: str
    api_key: Optional[str] = None
    model: str = "Qwen/Qwen2.5-3B-Instruct"
    max_new_tokens: int = 128
    temperature: float = 0.7
    timeout: int = 120  # seconds
    max_retries: int = 3
    retry_delay: float = 1.0

    def __post_init__(self):
        if not self.api_key:
            self.api_key = os.getenv("RUNPOD_API_KEY")
        if not self.endpoint_id:
            self.endpoint_id = os.getenv("RUNPOD_LLM_ENDPOINT", "")


class RunPodLLMClient:
    """Client for RunPod vLLM serverless endpoint.

    Provides OpenAI-compatible chat completions interface.
    """

    def __init__(self, cfg: RunPodLLMConfig):
        self.cfg = cfg
        self.enabled = bool(cfg.endpoint_id and cfg.api_key)
        self._base_url = f"https://api.runpod.ai/v2/{cfg.endpoint_id}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

    def _call_endpoint(self, payload: dict, sync: bool = True) -> dict:
        """Call RunPod endpoint with retry logic."""
        url = f"{self._base_url}/{'runsync' if sync else 'run'}"

        for attempt in range(self.cfg.max_retries):
            try:
                resp = requests.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.cfg.timeout,
                )
                resp.raise_for_status()
                data = resp.json()

                # Handle async job status polling
                if not sync and data.get("id"):
                    return self._poll_job(data["id"])

                # Check for RunPod-level errors
                if data.get("error"):
                    raise RuntimeError(f"RunPod error: {data['error']}")

                return data.get("output", data)

            except requests.exceptions.Timeout:
                if attempt < self.cfg.max_retries - 1:
                    time.sleep(self.cfg.retry_delay * (2**attempt))
                    continue
                raise
            except requests.exceptions.RequestException as e:
                if attempt < self.cfg.max_retries - 1:
                    time.sleep(self.cfg.retry_delay * (2**attempt))
                    continue
                raise RuntimeError(f"RunPod request failed: {e}") from e

        raise RuntimeError("Max retries exceeded")

    def _poll_job(self, job_id: str, poll_interval: float = 0.5) -> dict:
        """Poll for async job completion."""
        url = f"{self._base_url}/status/{job_id}"
        start = time.time()

        while time.time() - start < self.cfg.timeout:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status", "").upper()
            if status == "COMPLETED":
                return data.get("output", data)
            elif status in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"RunPod job {status}: {data.get('error', 'unknown')}")

            time.sleep(poll_interval)

        raise RuntimeError("Job polling timeout")

    def generate(self, system: str, user_text: str) -> str:
        """Generate a response from system prompt and user text."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        return self.generate_from_messages(messages)

    def generate_from_messages(self, messages: List[Dict[str, Any]]) -> str:
        """Generate a response from a list of messages.

        vLLM on RunPod uses OpenAI-compatible format.
        """
        if not self.enabled:
            return "(RunPod LLM not configured)"

        payload = {
            "input": {
                "messages": messages,
                "max_tokens": self.cfg.max_new_tokens,
                "temperature": self.cfg.temperature,
            }
        }

        result = self._call_endpoint(payload, sync=True)

        # vLLM returns OpenAI-style response
        if isinstance(result, dict):
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            # Some vLLM configs return text directly
            if "text" in result:
                return result["text"].strip()

        return str(result).strip() if result else ""

    def stream_from_messages(self, messages: List[Dict[str, Any]]) -> Iterator[str]:
        """Stream response chunks.

        Note: RunPod serverless doesn't support true streaming, so this
        falls back to returning the full response as a single chunk.
        For true streaming, use the /stream endpoint if available.
        """
        if not self.enabled:
            yield "(RunPod LLM not configured)"
            return

        # Try streaming endpoint first
        url = f"{self._base_url}/runsync"
        payload = {
            "input": {
                "messages": messages,
                "max_tokens": self.cfg.max_new_tokens,
                "temperature": self.cfg.temperature,
                "stream": True,
            }
        }

        try:
            with requests.post(
                url,
                headers=self._headers(),
                json=payload,
                stream=True,
                timeout=self.cfg.timeout,
            ) as resp:
                resp.raise_for_status()

                # If streaming works, yield chunks
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue

        except Exception:
            # Fall back to non-streaming
            text = self.generate_from_messages(messages)
            if text:
                yield text


# ---------------------------------------------------------------------------
# TTS Client (Kokoro on RunPod)
# ---------------------------------------------------------------------------


@dataclass
class RunPodTTSConfig:
    """Configuration for RunPod TTS endpoint."""

    endpoint_id: str
    api_key: Optional[str] = None
    voice: str = "af_heart"
    sample_rate: int = 24000
    timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0

    def __post_init__(self):
        if not self.api_key:
            self.api_key = os.getenv("RUNPOD_API_KEY")
        if not self.endpoint_id:
            self.endpoint_id = os.getenv("RUNPOD_TTS_ENDPOINT", "")


class RunPodTTSClient:
    """Client for RunPod Kokoro TTS serverless endpoint."""

    def __init__(self, cfg: RunPodTTSConfig):
        self.cfg = cfg
        self.enabled = bool(cfg.endpoint_id and cfg.api_key)
        self._base_url = f"https://api.runpod.ai/v2/{cfg.endpoint_id}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

    def _call_endpoint(self, payload: dict) -> dict:
        """Call RunPod endpoint with retry logic."""
        url = f"{self._base_url}/runsync"

        for attempt in range(self.cfg.max_retries):
            try:
                resp = requests.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.cfg.timeout,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("error"):
                    raise RuntimeError(f"RunPod error: {data['error']}")

                return data.get("output", data)

            except requests.exceptions.Timeout:
                if attempt < self.cfg.max_retries - 1:
                    time.sleep(self.cfg.retry_delay * (2**attempt))
                    continue
                raise
            except requests.exceptions.RequestException as e:
                if attempt < self.cfg.max_retries - 1:
                    time.sleep(self.cfg.retry_delay * (2**attempt))
                    continue
                raise RuntimeError(f"RunPod TTS request failed: {e}") from e

        raise RuntimeError("Max retries exceeded")

    def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        """Synthesize text to audio bytes (WAV format).

        Args:
            text: Text to synthesize
            voice: Voice ID (default: config voice)

        Returns:
            WAV audio bytes
        """
        if not self.enabled:
            raise RuntimeError("RunPod TTS not configured")

        if not text.strip():
            raise ValueError("No text provided")

        payload = {
            "input": {
                "text": text,
                "voice": voice or self.cfg.voice,
                "sample_rate": self.cfg.sample_rate,
            }
        }

        result = self._call_endpoint(payload)

        if isinstance(result, dict):
            if "error" in result:
                raise RuntimeError(f"TTS error: {result['error']}")

            audio_b64 = result.get("audio_base64")
            if audio_b64:
                return base64.b64decode(audio_b64)

        raise RuntimeError("Invalid TTS response format")

    def synthesize_to_file(
        self, text: str, out_path: str, voice: Optional[str] = None
    ) -> None:
        """Synthesize text and save to a WAV file.

        Args:
            text: Text to synthesize
            out_path: Output file path
            voice: Voice ID (default: config voice)
        """
        audio_bytes = self.synthesize(text, voice)
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
