# app/agents/planner_agent.py
import json
import re
from app.agents.base_agent import BaseAgent
from app.utils.logger import logger

class PlannerAgent(BaseAgent):
    """
    Agent spécialisé dans la planification de tâches complexes.
    Reçoit une demande en langage naturel et génère un plan d'exécution JSON.
    """

    def __init__(self, llm_service, bus, config):
        super().__init__("Planner", llm_service, bus)
        self.available_agents = config.get("agents", [])
        logger.info(f"📋 Agent planificateur initialisé avec {len(self.available_agents)} agents disponibles")

    def can_handle(self, query: str) -> bool:
        """Détecte si la requête nécessite une planification."""
        keywords = [
            "automatise", "chaque jour", "tous les", "quand", "si", "planifie",
            "programme", "répète", "quotidien", "hebdomadaire", "scénario"
        ]
        return any(kw in query.lower() for kw in keywords)

    def handle(self, query: str) -> str:
        """Génère un plan et le place dans le bus pour exécution."""
        plan = self._generate_plan(query)
        if not plan:
            return "Je n'ai pas réussi à créer un plan pour cette demande."

        # Stocker le plan dans le bus (clé "current_plan")
        self.bus.set("current_plan", plan)
        logger.info(f"✅ Plan généré avec {len(plan.get('steps', []))} étapes")
        return f"✅ Plan généré. Je vais l'exécuter maintenant."

    def _generate_plan(self, query: str) -> dict:
        """
        Interroge le LLM pour obtenir un plan structuré en JSON.
        """
        agents_list = ", ".join(self.available_agents) if self.available_agents else "aucun agent spécialisé (utiliser le LLM général)"

        prompt = f"""
Tu es un expert en planification d'automatisations. Voici une demande utilisateur :
"{query}"

Les agents disponibles sont : {agents_list}.

Génère un plan au format JSON avec la structure suivante :
{{
    "name": "nom de l'automatisation",
    "trigger": {{
        "type": "schedule" | "event" | "manual",
        "details": {{}}  # par exemple pour schedule : "interval": "daily", "time": "20:00"
    }},
    "steps": [
        {{
            "step_id": 1,
            "agent": "nom_agent",
            "action": "action à effectuer",
            "params": {{}},
            "depends_on": []  # liste des step_id dont cette étape dépend
        }},
        ...
    ]
}}

Le plan doit être réaliste et utilisable par les agents existants.
Si aucun agent n'est adapté, tu peux utiliser l'agent "general" qui correspond au LLM par défaut.
Réponds uniquement avec le JSON, sans commentaire.
"""
        try:
            response = self.ask_llm(prompt, system_prompt="Tu génères des plans d'automatisation en JSON.")
            # Nettoyer la réponse
            cleaned = response.strip().replace("```json", "").replace("```", "").strip()
            # Essayer de parser le JSON
            try:
                plan = json.loads(cleaned)
            except json.JSONDecodeError:
                # Tenter d'extraire avec regex
                match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if match:
                    plan = json.loads(match.group())
                else:
                    logger.error(f"Réponse non JSON reçue: {cleaned[:200]}")
                    return None
            return plan
        except Exception as e:
            logger.error(f"Erreur lors de la génération du plan : {e}")
            return None