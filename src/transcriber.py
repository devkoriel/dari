from __future__ import annotations

import structlog
import httpx

log = structlog.get_logger()

GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


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

    async def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str | None:
        if not self._enabled:
            return None

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
            log.exception("transcription_failed")
            return None
