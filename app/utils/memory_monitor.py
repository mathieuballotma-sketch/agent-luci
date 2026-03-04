"""
Surveillance mémoire du processus.
Met à jour une jauge Prometheus avec l'utilisation mémoire RSS.
"""

import threading
import time
import psutil
from .metrics import memory_usage_bytes
from ..utils.logger import logger

def monitor_memory(interval: int = 60):
    """
    Fonction à exécuter dans un thread pour surveiller la mémoire.
    Met à jour la jauge memory_usage_bytes toutes les `interval` secondes.
    """
    def _run():
        while True:
            try:
                mem = psutil.Process().memory_info().rss
                memory_usage_bytes.set(mem)
            except Exception as e:
                logger.debug(f"Erreur lors de la surveillance mémoire: {e}")
            time.sleep(interval)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info(f"📈 Surveillance mémoire démarrée (intervalle {interval}s)")