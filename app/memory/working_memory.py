"""
Mémoire de travail : buffer circulaire contenant le contexte récent de la conversation.
Accessible par tous les agents pour maintenir une cohérence.
"""

import time
from collections import deque
from typing import List, Dict, Any, Optional
import threading
from ..utils.metrics import set_working_memory_size


class WorkingMemory:
    """
    Mémoire de travail à court terme.
    Stocke les dernières interactions (requête + réponse) avec timestamp.
    """

    def __init__(self, capacity: int = 10):
        self.capacity = capacity
        self._buffer = deque(maxlen=capacity)
        self._lock = threading.RLock()

    def add(self, query: str, response: str, metadata: Optional[Dict] = None):
        """
        Ajoute une interaction dans la mémoire de travail.
        Met à jour la métrique de taille.
        """
        with self._lock:
            self._buffer.append({
                'query': query,
                'response': response,
                'timestamp': time.time(),
                'metadata': metadata or {}
            })
            set_working_memory_size(len(self._buffer))

    def get_recent(self, n: Optional[int] = None) -> List[Dict]:
        """
        Récupère les n dernières interactions (par défaut toutes).
        """
        with self._lock:
            if n is None:
                return list(self._buffer)
            return list(self._buffer)[-n:]

    def get_context_text(self, n: int = 5, include_metadata: bool = False) -> str:
        """
        Génère un texte formaté du contexte récent pour injection dans les prompts.
        """
        with self._lock:
            recent = list(self._buffer)[-n:]
            if not recent:
                return ""

            lines = []
            for i, item in enumerate(recent, 1):
                lines.append(f"--- Échange {i} ---")
                lines.append(f"Utilisateur: {item['query']}")
                lines.append(f"Assistant: {item['response']}")
                if include_metadata and item['metadata']:
                    lines.append(f"Métadonnées: {item['metadata']}")
                lines.append("")

            return "\n".join(lines)

    def clear(self):
        """Vide la mémoire de travail."""
        with self._lock:
            self._buffer.clear()
            set_working_memory_size(0)

    def get_stats(self) -> dict:
        """Statistiques."""
        with self._lock:
            return {
                'capacity': self.capacity,
                'current_size': len(self._buffer),
            }
    