import json
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

    async def ask(self, user_text: str, user_id: int | None = None, webhook_url: str | None = None, chat_id: int | None = None) -> str:
        if not self.is_configured():
            return "Integração Manus não configurada. Defina MANUS_API_URL e MANUS_API_KEY no Render."

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
            
        # Adicionamos a configuração do Webhook do Manus para ele nos avisar quando terminar
        if webhook_url and chat_id:
            payload["webhook"] = webhook_url
            # Podemos passar o chat_id no metadata ou na URL para saber para quem responder depois
            # A forma mais garantida é colocar como parâmetro na URL do webhook
            if "?" in webhook_url:
                payload["webhook"] = f"{webhook_url}&chat_id={chat_id}"
            else:
                payload["webhook"] = f"{webhook_url}?chat_id={chat_id}"

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.post(self.base_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                return f"Erro ao criar tarefa no Manus: {str(e)}"

        if not isinstance(data, dict):
            return "Recebi uma resposta inválida da API do Manus."

        if "error" in data:
            return f"Erro do Manus: {data['error']}"
        if "detail" in data:
            return f"Detalhe do Manus: {data['detail']}"

        # Se enviamos um webhook, o Manus só vai nos retornar o task_id e o aviso de que começou
        if "task_id" in data and webhook_url:
            return "⏳ O Manus começou a trabalhar na sua tarefa e enviará a resposta aqui quando terminar!"
            
        # Se não configuramos webhook ou a API retornou direto
        for key in ("reply", "response", "answer", "text", "output", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        try:
            raw_json = json.dumps(data, indent=2)
            return f"Retorno desconhecido da API do Manus:\n```\n{raw_json}\n```"
        except Exception:
            return f"Recebi a resposta do Manus, mas não consegui interpretar o formato: {data}"
