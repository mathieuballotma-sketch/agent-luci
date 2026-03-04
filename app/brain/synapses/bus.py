"""
Bus de synapse - Partage de contexte entre les composants du cerveau.
Permet de stocker et récupérer un contexte partagé de manière thread-safe.
"""

import threading
import time
from ...utils.logger import logger

class SynapseBus:
    """
    Bus de contexte partagé entre les différentes parties du cerveau.
    Stocke un contexte textuel (ex: dernière pensée, plan en cours) et
    permet de vérifier sa fraîcheur.
    """

    def __init__(self):
        self._context: str = ""
        self._lock = threading.RLock()
        self._last_update: float = 0
        self._update_count: int = 0

    def update(self, text: str) -> None:
        """
        Met à jour le contexte partagé.
        Thread-safe.
        """
        with self._lock:
            old_len = len(self._context)
            self._context = text
            self._last_update = time.time()
            self._update_count += 1
            logger.debug(f"BUS: mise à jour (ancien: {old_len}, nouveau: {len(text)})")

    def get_context(self) -> str:
        """
        Retourne le contexte actuel.
        Thread-safe.
        """
        with self._lock:
            return self._context

    def get_age(self) -> float:
        """
        Retourne l'âge du contexte en secondes.
        Retourne l'infini si jamais mis à jour.
        """
        with self._lock:
            return time.time() - self._last_update if self._last_update else float('inf')

    def is_fresh(self, max_age: float = 15.0) -> bool:
        """
        Vérifie si le contexte a été mis à jour récemment.
        Par défaut, considère frais un contexte de moins de 15 secondes.
        """
        return self.get_age() < max_age

    def get_stats(self) -> dict:
        """
        Retourne des statistiques sur le bus.
        """
        with self._lock:
            return {
                "age": self.get_age(),
                "update_count": self._update_count,
                "context_length": len(self._context)
            }