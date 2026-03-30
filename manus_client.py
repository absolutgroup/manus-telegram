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

        # Se retornou um task_id, vamos fazer o polling!
        if "task_id" in data:
            task_id = data["task_id"]
            return await self._poll_task_result(task_id, headers)
            
        # Fallback caso ele responda direto (se um dia a API mudar)
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
        """Fica checando o status da tarefa a cada 5 segundos até concluir ou dar timeout (limite de 3 minutos)."""
        max_attempts = 36  # 36 tentativas * 5 segundos = 3 minutos
        
        # O endpoint para ver a task geralmente é /v1/tasks/{task_id} ou similar.
        # Vamos assumir que base_url é algo como https://api.manus.ai/v1/tasks
        # Então a URL de status seria {base_url}/{task_id}
        status_url = f"{self.base_url}/{task_id}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(max_attempts):
                await asyncio.sleep(5)  # Espera 5 segundos antes de checar
                
                try:
                    response = await client.get(status_url, headers=headers)
                    response.raise_for_status()
                    task_data = response.json()
                    
                    status = task_data.get("status", "").lower()
                    
                    if status in ("completed", "done", "success", "finished"):
                        # Tenta pegar o resultado final
                        result = task_data.get("result", "")
                        if result:
                            return result
                        
                        # Se não tem 'result', tenta outras chaves comuns
                        for key in ("response", "answer", "output", "message"):
                            val = task_data.get(key)
                            if val and isinstance(val, str):
                                return val
                                
                        return f"Tarefa {task_id} concluída, mas o resultado estava vazio ou em formato não esperado."
                        
                    elif status in ("failed", "error", "canceled"):
                        error_msg = task_data.get("error", "Erro desconhecido")
                        return f"A tarefa do Manus falhou. Motivo: {error_msg}"
                        
                    # Se for "processing", "pending", "running", continua o loop
                    
                except Exception as e:
                    # Pode ser erro de rede momentâneo, continua tentando
                    print(f"Erro ao checar status da tarefa {task_id}: {e}")
                    
            return f"⏳ O Manus está demorando muito para responder (mais de 3 minutos). Você pode checar o resultado manualmente aqui: https://manus.im/app/{task_id}"
