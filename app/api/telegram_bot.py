# app/api/telegram_bot.py
"""
Module pour intégrer un bot Telegram avec Agent Lucide.
Version robuste avec logs détaillés et désactivation du RAG.
"""

import asyncio
import logging
import requests
from fastapi import FastAPI, Request
import threading
import uvicorn
from ..core.engine import LucidEngine
from ..utils.logger import logger

# Configuration du logging pour voir les erreurs
logging.basicConfig(level=logging.INFO)


class TelegramBot:
    """
    Gère les interactions avec Telegram via webhook.
    """

    def __init__(self, engine: LucidEngine, token: str, webhook_url: str, port: int = 8002):
        self.engine = engine
        self.token = token
        self.webhook_url = webhook_url
        self.port = port
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.app = FastAPI()
        self._setup_routes()

    def _setup_routes(self):
        @self.app.post(f"/webhook/{self.token}")
        async def telegram_webhook(request: Request):
            """
            Reçoit les updates de Telegram.
            """
            try:
                update = await request.json()
                logger.info(f"🟢 Webhook reçu: {update}")

                if "message" in update:
                    chat_id = update["message"]["chat"]["id"]
                    text = update["message"].get("text", "")
                    logger.info(f"📩 Message de {chat_id}: {text}")

                    # Vérifier que le moteur a bien la méthode process_async
                    if not hasattr(self.engine, 'process_async'):
                        error_msg = "Erreur: engine n'a pas de méthode process_async"
                        logger.error(error_msg)
                        await self._send_message(chat_id, error_msg)
                        return {"ok": False, "error": error_msg}

                    # Appeler l'agent (avec use_rag=False pour éviter les dépendances lourdes)
                    try:
                        response, latency = await self.engine.process_async(
                            query=text,
                            use_rag=False  # ← désactive le RAG pour Telegram
                        )
                        logger.info(f"🤖 Réponse obtenue en {latency:.2f}s: {response[:100]}...")
                        await self._send_message(chat_id, response)
                    except Exception as e:
                        logger.exception(f"❌ Erreur lors du traitement: {e}")
                        await self._send_message(chat_id, f"Erreur interne: {e}")

                return {"ok": True}

            except Exception as e:
                logger.exception(f"❌ Erreur dans le webhook: {e}")
                return {"ok": False, "error": str(e)}

        @self.app.get("/health")
        async def health():
            return {"status": "ok"}

    async def _send_message(self, chat_id: int, text: str):
        """Envoie un message via l'API Telegram."""
        url = f"{self.api_url}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: requests.post(url, json=payload, timeout=10)
            )
            if response.status_code != 200:
                logger.error(f"Erreur envoi message Telegram: {response.text}")
        except Exception as e:
            logger.error(f"Exception envoi message: {e}")

    def set_webhook(self):
        """Configure le webhook auprès de Telegram."""
        url = f"{self.api_url}/setWebhook"
        try:
            response = requests.post(url, json={"url": self.webhook_url}, timeout=10)
            if response.status_code == 200:
                logger.info("✅ Webhook Telegram configuré")
            else:
                logger.error(f"❌ Erreur configuration webhook: {response.text}")
        except Exception as e:
            logger.error(f"❌ Exception configuration webhook: {e}")

    def start(self):
        """Démarre le serveur FastAPI pour le bot dans un thread."""
        def run():
            uvicorn.run(self.app, host="0.0.0.0", port=self.port)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        logger.info(f"✅ Bot Telegram démarré sur le port {self.port}")