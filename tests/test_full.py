#!/usr/bin/env python3
# tests/test_full.py

import sys
import os
import time
import traceback
from pathlib import Path

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import Config
from app.core.engine import LucidEngine
from app.utils.logger import logger
from app.memory import MemoryService
from app.agents.reminder_agent import ReminderAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.document_agent import DocumentAgent
from app.agents.vision.text_extractor import TextExtractorAgent
from app.agents.profile_agent import ProfileAgent
from app.services.prompt_cache import PromptCache

class TestSuite:
    def __init__(self):
        self.config = None
        self.engine = None
        self.errors = []
        self.successes = []

    def run(self):
        print("="*60)
        print("🧪 TEST COMPLET DE L'AGENT LUCIDE")
        print("="*60)

        self.test_config_loading()
        self.test_engine_initialization()
        self.test_agents()
        self.test_memory()
        self.test_cache()
        self.test_elasticity()
        self.test_rag()
        self.test_actions()
        self.test_profile_agent()
        self.test_simple_query()
        self.test_complex_query()
        self.test_shutdown()

        self.print_summary()

    def report(self, test_name, success, error=None):
        if success:
            self.successes.append(test_name)
            print(f"✅ {test_name}")
        else:
            self.errors.append((test_name, error))
            print(f"❌ {test_name} - {error}")

    def test_config_loading(self):
        try:
            self.config = Config.load()
            assert self.config is not None
            assert self.config.app.name == "Lucid Agent"
            self.report("Chargement de la configuration", True)
        except Exception as e:
            self.report("Chargement de la configuration", False, str(e))

    def test_engine_initialization(self):
        try:
            if not self.config:
                raise Exception("Configuration non chargée")
            self.engine = LucidEngine(self.config)
            assert self.engine is not None
            self.report("Initialisation du moteur", True)
        except Exception as e:
            self.report("Initialisation du moteur", False, str(e))

    def test_agents(self):
        if not self.engine:
            self.report("Test des agents", False, "Moteur non initialisé")
            return

        try:
            # Vérifier que tous les agents sont enregistrés
            agents = self.engine.cortex.agents
            expected_agents = ["ReminderAgent", "KnowledgeAgent", "DocumentAgent", "TextExtractorAgent"]
            for name in expected_agents:
                assert name in agents, f"Agent {name} manquant"
            self.report("Présence des agents", True)
        except Exception as e:
            self.report("Présence des agents", False, str(e))

        # Test ReminderAgent
        try:
            agent = self.engine.cortex.agents["ReminderAgent"]
            tools = agent.get_tools()
            assert len(tools) >= 1
            self.report("ReminderAgent - outils disponibles", True)
        except Exception as e:
            self.report("ReminderAgent - outils disponibles", False, str(e))

        # Test KnowledgeAgent
        try:
            agent = self.engine.cortex.agents["KnowledgeAgent"]
            tools = agent.get_tools()
            assert len(tools) >= 5  # web_search, wikipedia_summary, wikipedia_search, arxiv_search, news_headlines
            self.report("KnowledgeAgent - outils disponibles", True)
        except Exception as e:
            self.report("KnowledgeAgent - outils disponibles", False, str(e))

        # Test DocumentAgent
        try:
            agent = self.engine.cortex.agents["DocumentAgent"]
            tools = agent.get_tools()
            assert len(tools) >= 1
            self.report("DocumentAgent - outils disponibles", True)
        except Exception as e:
            self.report("DocumentAgent - outils disponibles", False, str(e))

        # Test TextExtractorAgent
        try:
            agent = self.engine.cortex.agents["TextExtractorAgent"]
            tools = agent.get_tools()
            assert len(tools) >= 3
            self.report("TextExtractorAgent - outils disponibles", True)
        except Exception as e:
            self.report("TextExtractorAgent - outils disponibles", False, str(e))

    def test_memory(self):
        if not self.engine:
            self.report("Test mémoire", False, "Moteur non initialisé")
            return

        try:
            # Vérifier que le service mémoire est présent
            assert hasattr(self.engine, 'memory')
            assert isinstance(self.engine.memory, MemoryService)
            self.report("Service mémoire présent", True)
        except Exception as e:
            self.report("Service mémoire présent", False, str(e))

        try:
            # Ajouter un souvenir
            self.engine.memory.add_to_working("test query", "test response")
            self.engine.memory.add_episode("test query", "test response", {"test": True})
            self.report("Ajout en mémoire", True)
        except Exception as e:
            self.report("Ajout en mémoire", False, str(e))

        try:
            # Récupérer le contexte
            context = self.engine.memory.get_working_context()
            assert isinstance(context, str)
            self.report("Récupération contexte", True)
        except Exception as e:
            self.report("Récupération contexte", False, str(e))

    def test_cache(self):
        if not self.engine:
            self.report("Test cache", False, "Moteur non initialisé")
            return

        try:
            cache = self.engine.prompt_cache
            assert isinstance(cache, PromptCache)
            self.report("Cache présent", True)
        except Exception as e:
            self.report("Cache présent", False, str(e))

        try:
            # Mettre en cache une réponse
            cache.put("test prompt", "test system", "test model", "test response")
            # Récupérer
            response = cache.get("test prompt", "test system", "test model")
            assert response == "test response"
            self.report("Cache exact fonctionnel", True)
        except Exception as e:
            self.report("Cache exact fonctionnel", False, str(e))

        try:
            # Test cache vectoriel pour les plans
            test_plan = [{"id": "1", "agent": "TestAgent", "tool": "test"}]
            cache.put_plan("test plan query", test_plan)
            plan = cache.get_plan("test plan query", similarity_threshold=0.9)
            assert plan is not None
            self.report("Cache vectoriel des plans fonctionnel", True)
        except Exception as e:
            self.report("Cache vectoriel des plans fonctionnel", False, str(e))

    def test_elasticity(self):
        if not self.engine:
            self.report("Test élasticité", False, "Moteur non initialisé")
            return

        try:
            # Vérifier que l'elasticity engine est présent
            assert hasattr(self.engine, 'elasticity')
            self.report("Moteur d'élasticité présent", True)
        except Exception as e:
            self.report("Moteur d'élasticité présent", False, str(e))

        try:
            # Obtenir le modèle recommandé
            model = self.engine.elasticity.get_recommended_model()
            assert isinstance(model, str)
            assert model in ["qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b"]
            self.report("Recommandation de modèle fonctionnelle", True)
        except Exception as e:
            self.report("Recommandation de modèle fonctionnelle", False, str(e))

        try:
            # Obtenir le nombre de workers
            workers = self.engine.elasticity.get_max_workers()
            assert isinstance(workers, int)
            assert 1 <= workers <= 3
            self.report("Ajustement des workers fonctionnel", True)
        except Exception as e:
            self.report("Ajustement des workers fonctionnel", False, str(e))

    def test_rag(self):
        if not self.engine:
            self.report("Test RAG", False, "Moteur non initialisé")
            return

        try:
            assert hasattr(self.engine, 'rag')
            self.report("Service RAG présent", True)
        except Exception as e:
            self.report("Service RAG présent", False, str(e))

        try:
            # Tester une requête RAG (même si vide)
            result = self.engine.rag.query("test query")
            assert isinstance(result, str)
            self.report("Requête RAG fonctionnelle", True)
        except Exception as e:
            self.report("Requête RAG fonctionnelle", False, str(e))

    def test_actions(self):
        if not self.engine:
            self.report("Test actions", False, "Moteur non initialisé")
            return

        try:
            # Vérifier que le routeur d'actions est présent
            assert hasattr(self.engine, 'action_router')
            self.report("Routeur d'actions présent", True)
        except Exception as e:
            self.report("Routeur d'actions présent", False, str(e))

        try:
            # Simuler une action de création de document (sans vraiment créer)
            response = "ACTION: create_word_document|Test Titre|Test Contenu"
            executed, result = self.engine.action_router.parse_and_execute(response)
            assert executed is True
            assert "Document Word créé" in result or "Erreur" not in result
            self.report("Parsing d'action fonctionnel", True)
        except Exception as e:
            self.report("Parsing d'action fonctionnel", False, str(e))

    def test_profile_agent(self):
        if not self.engine:
            self.report("Test ProfileAgent", False, "Moteur non initialisé")
            return

        try:
            assert hasattr(self.engine, 'profile_agent')
            assert isinstance(self.engine.profile_agent, ProfileAgent)
            self.report("ProfileAgent présent", True)
        except Exception as e:
            self.report("ProfileAgent présent", False, str(e))

        try:
            # Récupérer le profil (même vide)
            profile = self.engine.profile_agent.get_profile()
            assert isinstance(profile, dict)
            self.report("Récupération du profil fonctionnelle", True)
        except Exception as e:
            self.report("Récupération du profil fonctionnelle", False, str(e))

    def test_simple_query(self):
        if not self.engine:
            self.report("Test requête simple", False, "Moteur non initialisé")
            return

        try:
            start = time.time()
            response, latency = self.engine.process("Quelle est la capitale de la France ?", use_rag=False)
            duration = time.time() - start
            assert isinstance(response, str)
            assert len(response) > 0
            assert latency <= duration + 0.1  # vérifier la cohérence
            self.report(f"Requête simple répondue en {duration:.2f}s", True)
        except Exception as e:
            self.report("Requête simple", False, str(e))

    def test_complex_query(self):
        if not self.engine:
            self.report("Test requête complexe", False, "Moteur non initialisé")
            return

        try:
            start = time.time()
            response, latency = self.engine.process("Crée un document Word sur l'IA", use_rag=False)
            duration = time.time() - start
            assert isinstance(response, str)
            assert len(response) > 0
            self.report(f"Requête complexe répondue en {duration:.2f}s", True)
        except Exception as e:
            self.report("Requête complexe", False, str(e))

    def test_shutdown(self):
        if not self.engine:
            self.report("Arrêt du moteur", False, "Moteur non initialisé")
            return

        try:
            self.engine.stop()
            self.report("Arrêt du moteur", True)
        except Exception as e:
            self.report("Arrêt du moteur", False, str(e))

    def print_summary(self):
        print("\n" + "="*60)
        print("📊 RÉSUMÉ DES TESTS")
        print("="*60)
        print(f"✅ Réussis : {len(self.successes)}")
        print(f"❌ Échecs : {len(self.errors)}")

        if self.errors:
            print("\nDétail des erreurs :")
            for name, error in self.errors:
                print(f"  - {name}: {error}")

        if self.successes:
            print("\nTests réussis :")
            for name in self.successes:
                print(f"  - {name}")

        print("="*60)

if __name__ == "__main__":
    suite = TestSuite()
    suite.run()