"""
Service de mémoire unifié : expose les deux mémoires (épisodique et travail)
et orchestre leur interaction.
"""

from typing import Optional, Dict, List
from .episodic_memory import EpisodicMemory
from .working_memory import WorkingMemory
from ..utils.logger import logger


class MemoryService:
    """
    Façade pour accéder aux différentes mémoires.
    """

    def __init__(self, episodic_memory: EpisodicMemory, working_memory: WorkingMemory):
        self.episodic = episodic_memory
        self.working = working_memory
        logger.info("🧠 Service mémoire initialisé")

    def remember(self, query: str, n_results: int = 3, min_similarity: float = 0.7) -> List[Dict]:
        """
        Récupère des souvenirs épisodiques similaires à la requête.
        """
        return self.episodic.search(query, n_results, min_similarity)

    def add_episode(self, query: str, response: str, metadata: Optional[Dict] = None):
        """
        Ajoute une interaction à la mémoire épisodique (asynchrone).
        """
        self.episodic.add(query, response, metadata)

    def add_to_working(self, query: str, response: str, metadata: Optional[Dict] = None):
        """
        Ajoute une interaction à la mémoire de travail.
        """
        self.working.add(query, response, metadata)

    def get_working_context(self, n: int = 5) -> str:
        """
        Récupère le contexte récent formaté.
        """
        return self.working.get_context_text(n=n)

    def get_stats(self) -> dict:
        """Statistiques combinées."""
        return {
            'episodic': self.episodic.get_stats(),
            'working': self.working.get_stats(),
        }