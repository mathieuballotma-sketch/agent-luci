#!/usr/bin/env python3
# main_hud.py - Point d'entrée HUD avec gestion des environnements

import sys
import os
import subprocess
import atexit
import signal
import time
import argparse
import shutil
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


def cleanup(api_process):
    """Nettoie le processus API à la sortie."""
    if api_process.poll() is None:
        api_process.terminate()
        api_process.wait()


def main():
    parser = argparse.ArgumentParser(description="Agent Lucide HUD")
    parser.add_argument('--config', default='config.yaml', help='Fichier de configuration à utiliser')
    parser.add_argument('--reset', action='store_true', help='Efface toutes les données persistantes avant de démarrer')
    args = parser.parse_args()

    # Chargement de la configuration
    config_path = args.config
    if not os.path.exists(config_path):
        print(f"❌ Fichier de configuration introuvable : {config_path}")
        sys.exit(1)

    try:
        cfg = Config.load(config_path)
        cfg.validate()
    except Exception as e:
        print(f"❌ Erreur de configuration : {e}")
        sys.exit(1)

    # Si reset est demandé, effacer les dossiers de données persistantes
    if args.reset:
        print("🧹 Réinitialisation des données persistantes...")
        data_dir = Path(cfg.app.data_dir)
        dirs_to_clear = [
            data_dir / "episodic_memory",
            data_dir / "cache",
            Path(cfg.rag.chroma_path) if cfg.rag.chroma_path else None
        ]
        for d in dirs_to_clear:
            if d and d.exists():
                shutil.rmtree(d)
                print(f"   Supprimé : {d}")
        print("✅ Données réinitialisées.")

    # Créer les dossiers nécessaires
    data_dir = Path(cfg.app.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    Path(cfg.app.logs_dir).mkdir(parents=True, exist_ok=True)

    logger.info("Démarrage de l'agent (HUD) avec config: %s", config_path)

    # Lancer l'API (optionnelle)
    api_process = start_api()
    atexit.register(cleanup, api_process)
    signal.signal(signal.SIGTERM, lambda sig, frame: cleanup(api_process))

    # Initialisation du moteur
    try:
        engine = LucidEngine(cfg)
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du moteur : {e}")
        sys.exit(1)

    # Démarrer le bot Telegram si le token est configuré
    if cfg.telegram.bot_token:
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