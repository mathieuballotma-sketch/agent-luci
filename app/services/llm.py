# app/services/llm.py
import time
import requests
from typing import Optional, Dict, Any
from ..utils.exceptions import LLMConnectionError, LLMTimeoutError, LLMResponseError, LLMModelNotFoundError
from ..utils.logger import logger

class LLMService:
    """Service de communication avec Ollama (LLM local)."""

    def __init__(self, host: str, default_model: str, timeout: int = 60,
                 retry_attempts: int = 2, retry_delay: float = 1.0):
        self.host = host.rstrip('/')
        self.default_model = default_model
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self._session = requests.Session()
        self._check_connection()

    def _check_connection(self):
        """Vérifie que le serveur Ollama est joignable au démarrage."""
        try:
            r = self._session.get(f"{self.host}/api/tags", timeout=5)
            if r.status_code != 200:
                raise LLMConnectionError(f"Ollama répond avec code {r.status_code}")
            logger.info("✅ Connexion à Ollama établie.")
        except requests.exceptions.ConnectionError:
            raise LLMConnectionError("Impossible de se connecter à Ollama. Vérifie qu'il tourne avec 'ollama serve'.")
        except Exception as e:
            raise LLMConnectionError(f"Erreur inattendue : {e}")

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Envoie une requête POST à Ollama avec gestion des timeouts."""
        url = f"{self.host}{endpoint}"
        for attempt in range(self.retry_attempts + 1):
            try:
                r = self._session.post(url, json=payload, timeout=self.timeout)
                if r.status_code == 404:
                    # Modèle non trouvé
                    raise LLMModelNotFoundError(f"Modèle '{payload.get('model')}' introuvable sur Ollama.")
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                if attempt < self.retry_attempts:
                    wait = self.retry_delay * (2 ** attempt)  # exponential backoff
                    logger.warning(f"Timeout, nouvelle tentative dans {wait:.1f}s...")
                    time.sleep(wait)
                else:
                    raise LLMTimeoutError(f"Le LLM n'a pas répondu après {self.retry_attempts+1} tentatives.")
            except requests.exceptions.RequestException as e:
                if attempt < self.retry_attempts:
                    wait = self.retry_delay * (2 ** attempt)
                    logger.warning(f"Erreur {e}, nouvelle tentative dans {wait:.1f}s...")
                    time.sleep(wait)
                else:
                    raise LLMResponseError(f"Échec de la requête LLM : {e}")

    def generate(self, system: str, user: str, model: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 2048) -> str:
        """Génère une réponse à partir d'un prompt système et utilisateur."""
        model = model or self.default_model
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            },
            "stream": False
        }
        logger.debug(f"Requête LLM (model={model}) : system={system[:50]}..., user={user[:50]}...")
        data = self._post("/api/chat", payload)
        response = data.get("message", {}).get("content", "").strip()
        if not response:
            raise LLMResponseError("Réponse vide du LLM.")
        logger.debug(f"Réponse LLM (taille={len(response)} chars)")
        return response

    def list_models(self) -> list:
        """Retourne la liste des modèles disponibles localement."""
        data = self._post("/api/tags", {})  # en réalité GET, mais on utilise un GET simple
        # Ici on utilise plutôt une requête GET, on va le faire à part
        try:
            r = self._session.get(f"{self.host}/api/tags", timeout=10)
            r.raise_for_status()
            models = r.json().get("models", [])
            return [m["name"] for m in models]
        except Exception as e:
            logger.error(f"Impossible de lister les modèles : {e}")
            return []

    def is_available(self) -> bool:
        """Ping rapide pour vérifier la disponibilité."""
        try:
            r = self._session.get(f"{self.host}/api/tags", timeout=2)
            return r.status_code == 200
        except:
            return False