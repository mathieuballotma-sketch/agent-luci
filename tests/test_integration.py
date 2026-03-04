#!/usr/bin/env python3
"""
Test d'intégration pour Agent Lucide.
Vérifie que tous les composants se chargent correctement et qu'une requête simple fonctionne.
"""

import sys
import time
import os
from pathlib import Path

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import Config
from app.core.engine import LucidEngine
from app.utils.logger import logger

def test_config_loading():
    """Teste le chargement de la configuration."""
    print("📁 Test 1: Chargement de la configuration...")
    try:
        config = Config.load("config.yaml")
        print(f"   ✅ Config chargée: {config.app.name} v{config.app.version}")
        return config
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        sys.exit(1)

def test_engine_initialization(config):
    """Teste l'initialisation du moteur."""
    print("\n🚀 Test 2: Initialisation du moteur...")
    try:
        engine = LucidEngine(config)
        print("   ✅ Moteur initialisé")
        return engine
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        sys.exit(1)

def test_simple_query(engine):
    """Teste une requête simple."""
    print("\n💬 Test 3: Requête simple...")
    query = "Quelle est la capitale de la France ?"
    try:
        response, latency = engine.process(query, use_rag=False)
        print(f"   ✅ Réponse reçue en {latency:.2f}s")
        print(f"   📝 Extrait: {response[:100]}...")
        return response
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        return None

def test_memory(engine):
    """Teste l'ajout en mémoire."""
    print("\n🧠 Test 4: Test mémoire...")
    try:
        # Ajouter un épisode manuellement
        engine.memory.add_episode("test query", "test response", {"test": True})
        print("   ✅ Épisode ajouté")
        # Vérifier la recherche
        results = engine.memory.remember("test", n_results=1)
        if results:
            print(f"   ✅ Recherche mémoire OK ({len(results)} résultats)")
        else:
            print("   ⚠️ Aucun résultat mémoire (normal si vide)")
        return True
    except Exception as e:
        print(f"   ❌ Erreur mémoire: {e}")
        return False

def test_profile_agent(engine):
    """Teste que le ProfileAgent tourne."""
    print("\n👤 Test 5: ProfileAgent...")
    try:
        if hasattr(engine, 'profile_agent'):
            profile = engine.profile_agent.get_profile()
            print(f"   ✅ ProfileAgent actif, dernière mise à jour: {profile.get('last_updated', 'jamais')}")
        else:
            print("   ⚠️ ProfileAgent non trouvé")
        return True
    except Exception as e:
        print(f"   ❌ Erreur ProfileAgent: {e}")
        return False

def test_elasticity(engine):
    """Teste l'élasticité."""
    print("\n📊 Test 6: Élasticité...")
    try:
        model = engine.elasticity.get_recommended_model()
        workers = engine.elasticity.get_max_workers()
        print(f"   ✅ Modèle recommandé: {model}, workers: {workers}")
        return True
    except Exception as e:
        print(f"   ❌ Erreur élasticité: {e}")
        return False

def main():
    print("="*60)
    print("🔍 TEST D'INTÉGRATION AGENT LUCIDE")
    print("="*60)

    config = test_config_loading()
    engine = test_engine_initialization(config)
    
    if engine:
        test_simple_query(engine)
        test_memory(engine)
        test_profile_agent(engine)
        test_elasticity(engine)
        
        # Nettoyage
        print("\n🧹 Arrêt du moteur...")
        engine.stop()
        print("✅ Moteur arrêté")
    
    print("\n" + "="*60)
    print("🏁 Tests terminés")
    print("="*60)

if __name__ == "__main__":
    main()
    