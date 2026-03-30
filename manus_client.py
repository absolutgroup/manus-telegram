import asyncio
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

    async def ask(self, user_text: str, user_id: int | None = None) -> str:
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

        # Se a API retornou um task_id, vamos iniciar o polling
        if "task_id" in data:
            task_id = data["task_id"]
            return await self._poll_task_result(task_id, headers)
            
        # Fallback se eles responderem na hora
        for key in ("reply", "response", "answer", "text", "output", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        try:
            raw_json = json.dumps(data, indent=2)
            return f"Retorno desconhecido da API do Manus:\n```\n{raw_json}\n```"
        except Exception:
            return f"Recebi a resposta do Manus, mas não consegui interpretar o formato: {data}"

    async def _poll_task_result(self, task_id: str, headers: dict) -> str:
        """Fica checando o status da tarefa a cada 10 segundos."""
        max_attempts = 30  # 30 * 10s = 5 minutos
        
        # O endpoint correto para checar o status de uma task no Manus
        # Documentação baseada no padrao REST deles: GET /v1/tasks/{task_id}
        status_url = f"{self.base_url}/{task_id}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(max_attempts):
                await asyncio.sleep(10)  # Espera 10 segundos
                
                try:
                    response = await client.get(status_url, headers=headers)
                    if response.status_code == 200:
                        task_data = response.json()
                        status = task_data.get("status", "").lower()
                        
                        if status in ("completed", "done", "success", "finished"):
                            # A resposta da task geralmente vem dentro de mensagens ou result
                            result = task_data.get("result", "")
                            if not result:
                                # Tenta pegar da lista de mensagens
                                messages = task_data.get("messages", [])
                                if messages and isinstance(messages, list):
                                    # Pega a última mensagem (geralmente a do assistente)
                                    last_msg = messages[-1]
                                    if isinstance(last_msg, dict) and "content" in last_msg:
                                        return last_msg["content"]
                                
                                # Fallback
                                for key in ("response", "answer", "output", "message", "content"):
                                    val = task_data.get(key)
                                    if val and isinstance(val, str):
                                        return val
                            else:
                                return result
                                
                            return f"Tarefa {task_id} concluída, mas não achei o texto.\n{json.dumps(task_data, indent=2)}"
                            
                        elif status in ("failed", "error", "canceled"):
                            error_msg = task_data.get("error", "Erro desconhecido")
                            return f"❌ A tarefa do Manus falhou. Motivo: {error_msg}"
                            
                except Exception as e:
                    print(f"Erro no polling da tarefa {task_id}: {e}")
                    
            return (
                f"⏳ O Manus está demorando muito para responder (mais de 5 minutos).\n\n"
                f"Você pode ver o resultado direto na plataforma:\n"
                f"https://manus.im/app/{task_id}"
            )
