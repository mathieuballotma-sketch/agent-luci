import time
import random
import hashlib
import httpx
from typing import List, Dict, Any, Optional, Callable
from ..utils.logger import logger

class SearchEngine:
    def __init__(self, name: str, search_func: Callable, cooldown: int = 60, max_retries: int = 3):
        self.name = name
        self.search_func = search_func
        self.cooldown = cooldown
        self.max_retries = max_retries
        self.failures = 0
        self.last_failure = 0
        self.is_available = True

    def mark_failure(self):
        self.failures += 1
        self.last_failure = time.time()
        if self.failures >= self.max_retries:
            self.is_available = False
            logger.warning(f"🔴 Moteur {self.name} temporairement désactivé après {self.failures} échecs")

    def mark_success(self):
        self.failures = 0
        self.is_available = True

    def can_use(self) -> bool:
        if not self.is_available:
            if time.time() - self.last_failure > self.cooldown:
                self.is_available = True
                self.failures = 0
                logger.info(f"🟢 Moteur {self.name} réactivé après cooldown")
                return True
            return False
        return True

class SearchManager:
    def __init__(self, cache_ttl: int = 300):
        self.engines: List[SearchEngine] = []
        self.cache: Dict[str, tuple] = {}
        self.cache_ttl = cache_ttl
        self.last_engine_index = -1

    def add_engine(self, name: str, search_func: Callable, cooldown: int = 60, max_retries: int = 3):
        self.engines.append(SearchEngine(name, search_func, cooldown, max_retries))

    def _get_cache_key(self, query: str) -> str:
        return hashlib.md5(query.encode()).hexdigest()

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        cache_key = self._get_cache_key(query)
        if cache_key in self.cache:
            results, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                logger.debug(f"📦 Résultats en cache pour '{query}'")
                return results
            else:
                del self.cache[cache_key]

        available_engines = [e for e in self.engines if e.can_use()]
        if not available_engines:
            logger.error("Aucun moteur de recherche disponible")
            return []

        self.last_engine_index = (self.last_engine_index + 1) % len(available_engines)
        engine = available_engines[self.last_engine_index]

        try:
            logger.info(f"🔍 Recherche avec {engine.name} pour '{query}'")
            results = engine.search_func(query, max_results)
            engine.mark_success()
            self.cache[cache_key] = (results, time.time())
            return results
        except Exception as e:
            logger.error(f"❌ Erreur avec {engine.name}: {e}")
            engine.mark_failure()
            return self.search(query, max_results)  # récursif mais limité par le nombre de moteurs

    def clear_cache(self):
        self.cache.clear()