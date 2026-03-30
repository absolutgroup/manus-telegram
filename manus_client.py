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
            payload["agentProfile"] = self.model

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return self._extract_text(data)

    def _extract_text(self, data: Any) -> str:
        if isinstance(data, str):
            return data

        if isinstance(data, dict):
            # NOVO: Tentar pegar status de erro ou detalhes que a API do Manus pode mandar quando dá pau
            if "error" in data:
                return f"Erro do Manus: {data['error']}"
            if "detail" in data:
                return f"Detalhe do Manus: {data['detail']}"

            # Tenta pegar apenas o ID da task (a API deles geralmente retorna a task criada em vez da resposta direta)
            if "id" in data and "status" in data:
                return f"Tarefa recebida pelo Manus! ID: {data['id']} - Status: {data['status']}\n(Nota: a API v1/tasks do Manus é assíncrona, ela cria a tarefa e você precisaria de outro endpoint para ler o resultado final. Retorno cru: {data})"

            # Tratamento exato para a API atual do Manus
            if "task_url" in data and "task_id" in data:
                return (
                    f"🤖 Manus está trabalhando na sua tarefa!\n\n"
                    f"Acompanhe o processo ou veja o resultado final aqui:\n"
                    f"{data['task_url']}"
                )

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

        # NOVO: Se ele não achar nenhum campo conhecido, imprime o JSON puro para vermos o que veio
        import json
        try:
            raw_json = json.dumps(data, indent=2)
            return f"Retorno desconhecido da API do Manus:\n```\n{raw_json}\n```"
        except Exception:
            return f"Recebi a resposta do Manus, mas não consegui interpretar o formato: {data}"
