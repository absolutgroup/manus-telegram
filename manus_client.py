import os
from typing import Any

import httpx


class ManusClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("MANUS_API_URL", "").strip()
        self.api_key = os.getenv("MANUS_API_KEY", "").strip()
        self.model = os.getenv("MANUS_MODEL", "").strip()
        self.timeout_seconds = float(os.getenv("MANUS_TIMEOUT_SECONDS", "45"))

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def ask(self, user_text: str, user_id: int | None = None) -> str:
        if not self.is_configured():
            return (
                "Integração Manus não configurada. Defina MANUS_API_URL e MANUS_API_KEY no Render."
            )

        headers = {
            "API_KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload: dict[str, Any] = {
            "prompt": user_text,
        }
        if user_id is not None:
            payload["user_id"] = str(user_id)
        if self.model:
            payload["model"] = self.model

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return self._extract_text(data)

    def _extract_text(self, data: Any) -> str:
        if isinstance(data, str):
            return data

        if isinstance(data, dict):
            for key in ("reply", "response", "answer", "text", "output", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        content = message.get("content")
                        if isinstance(content, str) and content.strip():
                            return content.strip()

        return "Recebi a resposta do Manus, mas não consegui interpretar o formato retornado."
