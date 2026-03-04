"""
Agent Stratège : analyse le contexte et propose des automatisations.
Tourne périodiquement et publie ses suggestions sur le bus d'événements.
Version avec deux modes : quick (rapide, peu de données) et deep (complet).
"""

import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent
from app.utils.logger import logger
from app.utils.metrics import strategist_suggestions_total


class SuggestionContract(BaseModel):
    """Contrat pour une suggestion d'automatisation."""
    title: str = Field(..., description="Titre court de la suggestion")
    description: str = Field(..., description="Description détaillée")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Niveau de confiance (0-1)")
    category: str = Field("productivity", description="Catégorie (productivity, organization, information, etc.)")
    cron_expression: Optional[str] = Field(None, description="Expression cron si tâche récurrente")
    query: Optional[str] = Field(None, description="Requête à exécuter pour la tâche")
    suggested_trigger: Optional[str] = Field(None, description="Description textuelle du déclencheur")
    suggested_action: Optional[str] = Field(None, description="Description textuelle de l'action")


class StrategistAgent(BaseAgent):
    """
    Agent qui analyse l'activité et propose des automatisations.
    Il n'est pas destiné à être appelé directement, mais à tourner périodiquement.
    """

    def __init__(self, llm_service, bus, event_bus, memory_service, config):
        super().__init__("StrategistAgent", llm_service, bus)
        self.event_bus = event_bus
        self.memory = memory_service
        self.config = config
        self.last_run = 0
        self.min_interval = config.get("strategist_interval", 3600)  # 1h par défaut

    def get_tools(self) -> list:
        return []  # Pas d'outils exposés aux utilisateurs

    def can_handle(self, query: str) -> bool:
        return False  # Non destiné à l'utilisateur

    async def handle(self, query: str) -> str:
        return "L'agent Stratège n'est pas destiné à être utilisé directement."

    async def run_periodic_review(self, mode: str = "balanced"):
        """
        Lance l'analyse stratégique.
        mode: "quick" (analyse rapide, peu de données), "deep" (analyse complète), "balanced" (compromis).
        """
        logger.info(f"🔍 Lancement de l'analyse stratégique (mode {mode})...")
        suggestions = await self._analyze(mode)
        for sug in suggestions:
            await self._publish_suggestion(sug)
        logger.info(f"✅ Analyse terminée, {len(suggestions)} suggestion(s) publiée(s)")

    async def _analyze(self, mode: str = "balanced") -> List[Dict[str, Any]]:
        """
        Analyse le contexte récent (mémoire de travail) et les souvenirs épisodiques
        pour générer des suggestions pertinentes.
        """
        if mode == "quick":
            working_context = self.memory.get_working_context(n=5)
            similar = []  # pas de recherche épisodique
            max_tokens = 256
            temperature = 0.5
        elif mode == "deep":
            working_context = self.memory.get_working_context(n=20)
            similar = self.memory.remember("stratégie automatisation", n_results=5)
            max_tokens = 512
            temperature = 0.7
        else:  # balanced
            working_context = self.memory.get_working_context(n=10)
            similar = self.memory.remember("stratégie automatisation", n_results=3)
            max_tokens = 384
            temperature = 0.6

        prompt = f"""
[Rôle] Tu es un stratège personnel. Ton objectif est d'augmenter la productivité de l'utilisateur en proposant des automatisations et des rappels.
[Contexte] Voici l'activité récente de l'utilisateur :
{working_context}
[Expériences similaires] Voici des souvenirs de stratégies passées :
{similar}
[Consignes] Analyse ce contexte. Identifie des tâches qui pourraient être automatisées (par exemple, ouvrir certaines applications à heures fixes, envoyer des rappels, rechercher des informations périodiquement). Propose des idées concrètes.
[Format de sortie] Réponds avec un JSON contenant une liste d'objets, chacun avec les champs suivants :
- title: titre court
- description: description détaillée
- confidence: nombre entre 0 et 1
- category: "productivity", "organization", "information", etc.
- cron_expression: (optionnel) expression cron valide si récurrente
- query: (optionnel) la requête à exécuter pour la tâche
- suggested_trigger: (optionnel) description textuelle du déclencheur
- suggested_action: (optionnel) description textuelle de l'action

Exemple:
[
  {{
    "title": "Consulter les actualités chaque matin",
    "description": "Ouvrir Safari et rechercher les actualités du jour à 8h",
    "confidence": 0.9,
    "category": "information",
    "cron_expression": "0 8 * * *",
    "query": "ouvre safari et cherche les actualités du jour"
  }}
]
Si aucune idée, retourne [].
"""
        try:
            response = await self.ask_llm_async(
                prompt,
                temperature=temperature,
                max_tokens=max_tokens
            )
            data = self.extract_json_from_response(response)
            if isinstance(data, list):
                return data
            else:
                logger.warning(f"Réponse inattendue du stratège: {response[:200]}")
                return []
        except Exception as e:
            logger.error(f"Erreur dans _analyze: {e}")
            return []

    async def _publish_suggestion(self, suggestion: Dict[str, Any]):
        """Publie une suggestion sur le bus d'événements et incrémente une métrique."""
        try:
            await self.event_bus.publish(
                event_type="strategist.suggestion",
                data=suggestion,
                source=self.name
            )
            logger.info(f"💡 Suggestion publiée: {suggestion.get('title')}")
            strategist_suggestions_total.labels(category=suggestion.get("category", "other")).inc()
        except Exception as e:
            logger.error(f"Erreur publication suggestion: {e}")