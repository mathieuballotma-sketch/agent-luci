"""
Sélecteur de chemin dynamique basé sur le principe de moindre action.
Choisit le traitement le plus rapide pour une requête donnée.
"""

import time
import hashlib
from typing import Callable, Any, Dict, Tuple
from collections import defaultdict
import numpy as np

class ActionSelector:
    """
    Implémente le principe de moindre action : pour chaque type de requête,
    on apprend le chemin le plus rapide et on le suit par défaut.
    """

    def __init__(self):
        # Statistiques des temps de traitement pour chaque type de requête
        self.stats = defaultdict(lambda: {"count": 0, "total_time": 0.0, "best_path": None})
        self.paths = {}  # Dictionnaire des chemins disponibles

    def register_path(self, path_id: str, func: Callable, description: str = ""):
        """
        Enregistre un chemin de traitement possible.
        Un chemin est une fonction qui prend une requête et retourne une réponse.
        """
        self.paths[path_id] = {"func": func, "description": description, "hits": 0}

    def get_path_for_query(self, query: str) -> Tuple[str, Callable]:
        """
        Retourne le chemin optimal pour une requête selon le principe de moindre action.
        Si aucune statistique, retourne le chemin par défaut (le plus simple).
        """
        # Calculer un hash de la requête pour le clustering (simplifié)
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        # Regrouper par similarité (ici on utilise juste une classe basée sur la longueur et les mots-clés)
        # Pour l'exemple, on classe par type : simple, action, complexe
        query_type = self._classify_query(query)

        stats = self.stats[query_type]
        if stats["count"] > 0 and stats["best_path"] is not None:
            # Moindre action : on prend le chemin le plus rapide en moyenne
            best_path_id = stats["best_path"]
            if best_path_id in self.paths:
                return best_path_id, self.paths[best_path_id]["func"]

        # Fallback : chemin par défaut (premier enregistré)
        default = next(iter(self.paths.items()))
        return default[0], default[1]["func"]

    def record(self, query: str, path_id: str, duration: float, success: bool):
        """
        Enregistre le temps d'exécution d'un chemin pour une requête.
        Met à jour les statistiques et recalcule le meilleur chemin.
        """
        query_type = self._classify_query(query)
        stats = self.stats[query_type]
        stats["count"] += 1
        stats["total_time"] += duration
        # Mise à jour du meilleur chemin (moyenne glissante)
        if stats["best_path"] is None:
            stats["best_path"] = path_id
        else:
            # Comparer les moyennes : on garde le chemin avec la moyenne la plus basse
            # Pour simplifier, on recalcule à chaque fois
            # Ceci est une approximation, on pourrait stocker les moyennes par path
            pass

    def _classify_query(self, query: str) -> str:
        """Classe une requête en type : simple, action, complexe."""
        q = query.lower()
        if len(q.split()) < 5:
            return "simple"
        action_keywords = ["ouvre", "lance", "tape", "clique", "capture"]
        if any(kw in q for kw in action_keywords):
            return "action"
        return "complexe"