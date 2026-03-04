#!/usr/bin/env python3
# main.py - Point d'entrée unique de l'agent Lucide

import sys
import time
from pathlib import Path

# Ajouter le chemin racine pour les imports
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import Config
from app.core.engine import LucidEngine
from app.services.audio import AudioService
from app.utils.logger import setup_logger
from app.agents.consolidator_agent import ConsolidatorAgent

def clear_screen():
    """Nettoie l'écran du terminal."""
    import os
    os.system('clear' if os.name == 'posix' else 'cls')

def print_header():
    """Affiche l'en-tête du programme."""
    print("=" * 60)
    print("           🤖 AGENT LUCIDE - MODE TERMINAL")
    print("=" * 60)

def main():
    print_header()
    
    # Chargement de la configuration
    try:
        cfg = Config.load("config.yaml")
        cfg.validate()
    except Exception as e:
        print(f"❌ Erreur de configuration : {e}")
        sys.exit(1)

    logger = setup_logger(cfg.app.logs_dir)
    logger.info("Démarrage de l'agent (terminal)")

    # Initialisation du moteur
    try:
        engine = LucidEngine(cfg)
        # Initialisation du consolidateur de mémoire
        consolidator = ConsolidatorAgent(engine.manager, engine.bus, {})
        consolidator.start_background_consolidation()
        logger.info("🧠 Consolidateur de mémoire lancé")
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du moteur : {e}")
        sys.exit(1)

    # Service audio (optionnel)
    try:
        audio_service = AudioService(cfg.audio)
        print("⏳ Chargement du modèle vocal en arrière-plan...")
    except Exception as e:
        logger.error(f"Erreur audio : {e}")
        audio_service = None

    print("\n✅ Agent prêt ! La vision, le RAG et la mémoire sont actifs.\n")

    # Boucle principale du menu
    while True:
        print("\n" + "-" * 40)
        print("MENU PRINCIPAL")
        print("1. Poser une question (mode texte)")
        print("2. Poser une question vocale (enregistrement 5s)")
        print("3. Indexer un fichier pour RAG")
        print("4. Indexer un dossier pour RAG")
        print("5. Quitter")
        print("-" * 40)

        choix = input("Votre choix [1-5] : ").strip()

        if choix == '1':
            query = input("\n💬 Votre question : ").strip()
            if not query:
                continue
            use_rag = input("Utiliser RAG ? (o/n) [o] : ").strip().lower() != 'n'
            print("\n🤔 Réflexion...")
            try:
                response, latency = engine.process(query, use_rag=use_rag)
                print(f"\n🤖 ({latency:.2f}s) : {response}\n")
            except Exception as e:
                print(f"\n❌ Erreur : {e}")

        elif choix == '2':
            if audio_service is None:
                print("❌ Service audio non disponible.")
                continue
            if not audio_service.is_ready():
                print("⏳ Modèle vocal pas encore prêt, veuillez patienter...")
                time.sleep(1)
                continue
            print("\n🎤 Parlez après le bip...")
            time.sleep(0.5)
            print("🔴 Enregistrement en cours (5 secondes)...")
            try:
                audio_service.start_recording()
                time.sleep(5)
                audio_path = audio_service.stop_recording()
                if not audio_path:
                    print("❌ Aucun son enregistré.")
                    continue
                print("⏳ Transcription...")
                query = audio_service.transcribe(audio_path)
                if not query:
                    print("❌ Transcription vide.")
                    continue
                print(f"📝 Vous avez dit : {query}")
                use_rag = input("Utiliser RAG ? (o/n) [o] : ").strip().lower() != 'n'
                print("🤔 Réflexion...")
                response, latency = engine.process(query, use_rag=use_rag)
                print(f"\n🤖 ({latency:.2f}s) : {response}\n")
            except Exception as e:
                print(f"❌ Erreur : {e}")

        elif choix == '3':
            path = input("Chemin du fichier : ").strip()
            if not path:
                continue
            print(f"⏳ Indexation de {path}...")
            success = engine.index_file(path)
            if success:
                print("✅ Indexation réussie.")
            else:
                print("❌ Échec de l'indexation.")

        elif choix == '4':
            path = input("Chemin du dossier : ").strip()
            if not path:
                continue
            print(f"⏳ Indexation du dossier {path}...")
            count = engine.index_folder(path)
            print(f"✅ {count} fichiers indexés.")

        elif choix == '5':
            print("\nArrêt de l'agent...")
            consolidator.stop()
            break

        else:
            print("❌ Choix invalide.")

    # Arrêt propre
    consolidator.stop()
    engine.stop()
    logger.info("Agent arrêté.")
    print("✅ Agent arrêté proprement. À bientôt !")

if __name__ == "__main__":
    main()