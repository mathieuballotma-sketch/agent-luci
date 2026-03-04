"""
Moteur de consolidation : apprentissage à partir des retours utilisateur.
Permet d'ajuster les poids ou de marquer les souvenirs comme importants.
"""

import time
import threading
from typing import Optional
from .episodic_memory import EpisodicMemory
from ..utils.logger import logger


class ConsolidationEngine:
    """
    Moteur de consolidation asynchrone.
    Pour l'instant, il se contente de mettre à jour les métadonnées (satisfaction).
    Plus tard, pourra déclencher un fine-tuning.
    """

    def __init__(self, episodic_memory: EpisodicMemory, interval: int = 3600):
        self.episodic = episodic_memory
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """Démarre le thread de consolidation."""
        if self._thread is None:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            logger.info("🔄 Moteur de consolidation démarré")

    def stop(self):
        """Arrête le thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
            logger.info("Moteur de consolidation arrêté")

    def _run(self):
        """Boucle principale de consolidation."""
        while not self._stop_event.is_set():
            # Pour l'instant, rien à faire. Plus tard, on pourra :
            # - Supprimer les souvenirs avec faible satisfaction
            # - Générer des résumés
            # - Lancer un apprentissage
            time.sleep(self.interval)

    def mark_satisfaction(self, query: str, response: str, rating: int):
        """
        Marque un souvenir avec un niveau de satisfaction (1-5).
        Pourrait être utilisé pour l'apprentissage par renforcement.
        """
        # Recherche le souvenir correspondant (approximatif)
        # C'est complexe car on n'a pas l'ID. Pour l'instant, on ignore.
        logger.debug(f"Satisfaction reçue pour '{query[:50]}': {rating}")
        # Idéalement, on stockerait cela dans les métadonnées.