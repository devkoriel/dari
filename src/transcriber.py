from __future__ import annotations

import asyncio

import httpx
import structlog

log = structlog.get_logger()

GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_RETRIES = 2
RETRY_BACKOFF = 1.0


class Transcriber:
    def __init__(self, groq_api_key: str) -> None:
        self._api_key = groq_api_key
        self._enabled = bool(groq_api_key)
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str | None:
        if not self._enabled:
            return None

        for attempt in range(MAX_RETRIES + 1):
            try:
                client = self._get_client()
                response = await client.post(
                    GROQ_WHISPER_URL,
                    files={"file": (filename, audio_bytes, "application/octet-stream")},
                    data={"model": "whisper-large-v3-turbo", "response_format": "text"},
                )
                response.raise_for_status()
                text = response.text.strip()
                if not text:
                    return None
                return text
            except Exception:
                if attempt < MAX_RETRIES:
                    log.warning("transcription_retry", attempt=attempt + 1)
                    await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
                    continue
                log.exception("transcription_failed")
                return None
