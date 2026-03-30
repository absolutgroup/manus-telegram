import os

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from manus_client import ManusClient

app = FastAPI(title="Telegram + Manus Bridge")
manus_client = ManusClient()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()


def _telegram_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


async def send_telegram_message(chat_id: int, text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não definido.")

    payload = {"chat_id": chat_id, "text": text}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(_telegram_api_url("sendMessage"), json=payload)
        resp.raise_for_status()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/setup-webhook", methods=["GET", "POST"])
async def setup_webhook(
    request: Request,
) -> JSONResponse:
    x_admin_token = request.headers.get("X-Admin-Token") or request.query_params.get("admin_token")
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_TOKEN não configurado no servidor.",
        )
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token de administração inválido.")

    base_url = str(request.base_url).rstrip("/")
    webhook_url = f"{base_url}/telegram/webhook/{TELEGRAM_WEBHOOK_SECRET}"

    payload = {"url": webhook_url}
    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(_telegram_api_url("setWebhook"), json=payload)
        
        # Log the error response from Telegram if it fails
        if resp.status_code != 200:
            error_details = resp.text
            print(f"TELEGRAM API ERROR: {error_details}")
            raise HTTPException(status_code=500, detail=f"Telegram API Error: {error_details}")
            
        resp.raise_for_status()
        telegram_response = resp.json()

    return JSONResponse(telegram_response)


@app.post("/telegram/webhook/{webhook_secret}")
async def telegram_webhook(
    webhook_secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> JSONResponse:
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN não configurado.")

    if TELEGRAM_WEBHOOK_SECRET and webhook_secret != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Webhook secret inválido.")

    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token:
        if x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Header secret inválido.")

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message:
        return JSONResponse({"ok": True, "ignored": "no-message"})

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "").strip()
    user_id = (message.get("from") or {}).get("id")

    if not chat_id:
        return JSONResponse({"ok": True, "ignored": "no-chat-id"})

    if not text:
        await send_telegram_message(chat_id, "Envie uma mensagem de texto para eu responder.")
        return JSONResponse({"ok": True, "ignored": "no-text"})

    # Quando recebemos uma mensagem, enviamos para o Manus passando a URL de callback (webhook)
    base_url = str(request.base_url).rstrip("/")
    manus_webhook_url = f"{base_url}/manus/webhook"

    try:
        reply_text = await manus_client.ask(
            text, 
            user_id=user_id, 
            webhook_url=manus_webhook_url, 
            chat_id=chat_id
        )
    except Exception as e:
        reply_text = f"Erro ao consultar o Manus: {str(e)}"

    if len(reply_text) > 4000:
        reply_text = reply_text[:4000]

    await send_telegram_message(chat_id, reply_text)
    
    return JSONResponse({"ok": True})

@app.post("/manus/webhook")
async def manus_webhook(request: Request) -> JSONResponse:
    """Recebe a resposta final do Manus quando a tarefa é concluída"""
    try:
        data = await request.json()
        print(f"WEBHOOK RECEBIDO DO MANUS: {data}")
        
        # O chat_id passamos pela URL do webhook
        chat_id_str = request.query_params.get("chat_id")
        if not chat_id_str:
            print("Erro: webhook recebido sem chat_id na query string")
            return JSONResponse({"error": "Missing chat_id"}, status_code=400)
            
        chat_id = int(chat_id_str)
        
        # A API do Manus pode mandar o status em diferentes lugares dependendo de como implementaram
        status = data.get("status", "").lower()
        
        # Se ele não enviar 'status', mas enviar um 'result', vamos assumir que deu certo
        if status in ("completed", "done", "success", "finished") or "result" in data or "response" in data:
            # Tenta pegar o resultado final
            result = data.get("result", "")
            if not result:
                for key in ("response", "answer", "output", "message", "content"):
                    val = data.get(key)
                    if val and isinstance(val, str):
                        result = val
                        break
                        
            if result:
                # O Telegram tem limite de 4096 caracteres por mensagem
                if len(result) > 4000:
                    # Envia em partes se for muito longo
                    for i in range(0, len(result), 4000):
                        part = result[i:i+4000]
                        await send_telegram_message(chat_id, part)
                else:
                    await send_telegram_message(chat_id, result)
            else:
                # Caiu aqui porque veio como 'completed' mas não achou o texto
                import json
                raw_data = json.dumps(data, indent=2)
                await send_telegram_message(chat_id, f"A tarefa terminou, mas o formato é diferente do esperado. Dados brutos:\n```\n{raw_data}\n```")
                
        elif status in ("failed", "error", "canceled"):
            error_msg = data.get("error", "Erro desconhecido")
            await send_telegram_message(chat_id, f"❌ A tarefa do Manus falhou. Motivo: {error_msg}")
        else:
            # Caso o status seja 'processing' ou algo assim que eles mandam como update parcial
            print(f"Webhook ignorado: status '{status}'")
            
        return JSONResponse({"ok": True})
        
    except Exception as e:
        print(f"Erro no webhook do Manus: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
