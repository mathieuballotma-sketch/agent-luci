#!/usr/bin/env python3
# main_hud.py - Point d'entrée HUD avec lancement automatique de l'API et bot Telegram

import sys
import os
import subprocess
import atexit
import signal
import time
from pathlib import Path

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import Config
from app.core.engine import LucidEngine
from app.api.telegram_bot import TelegramBot
from app.ui.hud_native import run_hud
from app.utils.logger import logger

def start_api():
    """Lance l'API de recherche locale en arrière-plan."""
    python_exe = sys.executable
    api_process = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "search_api.main:app", "--port", "8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2)  # Laisser le temps à l'API de démarrer
    return api_process

# Lancer l'API (optionnelle)
api_process = start_api()

def cleanup():
    """Nettoie le processus API à la sortie."""
    if api_process.poll() is None:
        api_process.terminate()
        api_process.wait()

atexit.register(cleanup)
signal.signal(signal.SIGTERM, lambda sig, frame: cleanup())

def main():
    # Chargement de la configuration
    cfg = Config.load("config.yaml")
    cfg.validate()

    # Initialisation du moteur
    engine = LucidEngine(cfg)

    # Démarrer le bot Telegram si le token est configuré
    if cfg.telegram.bot_token:
        # Construire l'URL du webhook
        # Soit on utilise webhook_base défini dans la config, soit on le passe manuellement
        if cfg.telegram.webhook_base:
            webhook_url = f"{cfg.telegram.webhook_base}/webhook/{cfg.telegram.bot_token}"
        else:
            logger.warning("⚠️ webhook_base non configuré, le bot Telegram ne pourra pas recevoir de messages sans ngrok.")
            webhook_url = None

        if webhook_url:
            bot = TelegramBot(engine, cfg.telegram.bot_token, webhook_url, port=8002)
            bot.set_webhook()
            bot.start()
        else:
            logger.warning("⚠️ Bot Telegram désactivé : webhook_base manquant.")
    else:
        logger.info("ℹ️ Token Telegram non fourni, bot désactivé.")

    # Lancer le HUD
    run_hud()

if __name__ == "__main__":
    main()