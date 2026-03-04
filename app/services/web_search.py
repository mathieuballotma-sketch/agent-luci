import asyncio
import logging
from typing import List, Dict, Optional
from ..utils.logger import get_logger

logger = get_logger(__name__)

# Tentative d'import de DuckDuckGo
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    try:
        from ddgs import DDGS
        DDGS_AVAILABLE = True
    except ImportError:
        DDGS_AVAILABLE = False
        logger.warning("⚠️ Module de recherche web non trouvé. Installez duckduckgo-search ou ddgs.")

class WebSearch:
    """Service de recherche internet asynchrone via DuckDuckGo."""

    def __init__(self):
        self._available = DDGS_AVAILABLE
        if self._available:
            logger.info("✅ WebSearch initialisé")
        else:
            logger.warning("⚠️ WebSearch non disponible")

    async def search(self, query: str, max_results: int = 3) -> List[Dict]:
        """
        Effectue une recherche web de manière asynchrone.
        Retourne une liste de dictionnaires avec les clés : title, body, url.
        """
        if not self._available:
            logger.error("Recherche web impossible : module manquant.")
            return []

        # Exécuter la recherche dans un thread séparé car DDGS est synchrone
        loop = asyncio.get_event_loop()
        try:
            results = await loop.run_in_executor(None, self._sync_search, query, max_results)
            return results
        except Exception as e:
            logger.error(f"Exception lors de la recherche web: {e}")
            return []

    def _sync_search(self, query: str, max_results: int) -> List[Dict]:
        """Version synchrone interne."""
        try:
            with DDGS() as ddgs:
                results = []
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        'title': r.get('title', ''),
                        'body': r.get('body', ''),
                        'url': r.get('href', '')
                    })
                return results
        except Exception as e:
            logger.error(f"Erreur dans _sync_search: {e}")
            return []

    async def search_with_fallback(self, query: str, max_results: int = 3, timeout: float = 5.0) -> List[Dict]:
        """
        Version avec timeout : si la recherche prend trop longtemps, retourne une liste vide.
        """
        try:
            return await asyncio.wait_for(self.search(query, max_results), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Recherche web timeout après {timeout}s pour '{query}'")
            return []