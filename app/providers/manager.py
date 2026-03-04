"""
Gestionnaire des fournisseurs LLM (Ollama).
Permet d'interagir avec les modèles locaux, avec gestion des erreurs, retries,
et option keep_alive pour maintenir le modèle en mémoire.
"""

import ollama
import time
from typing import Optional, Dict, Any
from ..utils.logger import logger
from ..utils.exceptions import LLMConnectionError, LLMTimeoutError, LLMModelNotFoundError


class ProviderManager:
    """
    Gère les appels aux modèles LLM via Ollama.
    Supporte plusieurs modèles (speed, balanced, quality, sentinel) et l'option keep_alive.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialise le gestionnaire avec la configuration.

        Args:
            config: Dictionnaire contenant les clés :
                - host: str, URL d'Ollama (ex: "http://localhost:11434")
                - models: dict, mapping des noms de profil vers des objets ModelConfig
                - timeout: int, timeout en secondes
                - retry_attempts: int, nombre de tentatives en cas d'échec
                - retry_delay: float, délai entre les tentatives
                - keep_alive: int, durée de maintien en mémoire (secondes, -1 pour indéfini)
        """
        self.config = config
        self.host = config.get("host", "http://localhost:11434")
        self.models = config.get("models", {})
        self.timeout = config.get("timeout", 30)
        self.retry_attempts = config.get("retry_attempts", 1)
        self.retry_delay = config.get("retry_delay", 0.5)
        self.keep_alive = config.get("keep_alive", -1)

        # Définir l'hôte pour la bibliothèque ollama
        ollama.host = self.host
        logger.info(f"ProviderManager initialisé avec host {self.host}, keep_alive={self.keep_alive}")

        # Vérifier la connexion au démarrage
        self._test_connection()

        # Pour le suivi des changements de modèle
        self._last_model = None

    def _test_connection(self):
        """Vérifie que le serveur Ollama est accessible et que les modèles sont disponibles."""
        try:
            models = ollama.list()
            models_available = [m['name'] for m in models.get('models', [])]
            logger.info(f"✅ Ollama accessible. Modèles disponibles: {models_available}")

            default_model = self._select_model("auto")
            if default_model and default_model not in models_available:
                logger.error(f"❌ Modèle par défaut '{default_model}' non trouvé. Téléchargez-le avec: ollama pull {default_model}")
            else:
                logger.info(f"✅ Modèle par défaut '{default_model}' disponible.")
        except Exception as e:
            logger.error(f"❌ Impossible de se connecter à Ollama: {e}")

    def generate(self, prompt: str, system: Optional[str] = None, priority: str = "auto",
                 model: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 512) -> str:
        """
        Génère une réponse à partir d'un prompt.
        """
        start_time = time.time()

        # Déterminer le modèle à utiliser
        if model:
            if model in self.models:
                model_obj = self.models[model]
                model_name = self._get_model_name(model_obj)
            else:
                model_name = model
        else:
            model_name = self._select_model(priority)

        if not model_name:
            logger.error("Aucun modèle disponible")
            return "[ERREUR] Aucun modèle LLM disponible"

        # Construire les messages
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Options pour Ollama
        options = {
            "num_predict": max_tokens,
            "temperature": temperature,
            "keep_alive": self.keep_alive,
        }

        logger.debug(f"Appel LLM - model: {model_name}, options: {options}")

        # Tentatives avec retry
        for attempt in range(self.retry_attempts + 1):
            try:
                response = ollama.chat(
                    model=model_name,
                    messages=messages,
                    options=options
                )
                elapsed = time.time() - start_time
                result = response['message']['content'].strip()
                logger.debug(f"Réponse LLM reçue en {elapsed:.2f}s (modèle: {model_name})")
                if self._last_model != model_name:
                    logger.info(f"Changement de modèle: {self._last_model} -> {model_name}")
                    self._last_model = model_name
                return result if result else "[RÉPONSE VIDE]"
            except Exception as e:
                logger.error(f"Tentative {attempt+1} échouée: {e}")
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    error_msg = f"[ERREUR Ollama] {e}"
                    if "not found" in str(e).lower():
                        raise LLMModelNotFoundError(f"Modèle '{model_name}' introuvable.")
                    elif "timeout" in str(e).lower():
                        raise LLMTimeoutError(f"Timeout après {self.retry_attempts+1} tentatives.")
                    else:
                        raise LLMConnectionError(f"Échec de communication: {e}")

        return "[ERREUR inconnue]"

    def _get_model_name(self, model) -> str:
        """Extrait le nom du modèle à partir d'un objet ModelConfig ou d'une chaîne."""
        if hasattr(model, 'name'):
            return model.name
        elif isinstance(model, dict):
            return model.get('name', '')
        else:
            return str(model)

    def _select_model(self, priority: str) -> Optional[str]:
        """
        Sélectionne un nom de modèle en fonction de la priorité.
        """
        if not self.models:
            return None

        if priority in self.models:
            model_obj = self.models[priority]
            return self._get_model_name(model_obj)

        # Sinon, on prend le premier modèle disponible
        for key, model in self.models.items():
            return self._get_model_name(model)

        return None

    def list_models(self) -> list:
        """Retourne la liste des modèles disponibles sur le serveur Ollama."""
        try:
            response = ollama.list()
            return [m['name'] for m in response.get('models', [])]
        except Exception as e:
            logger.error(f"Impossible de lister les modèles: {e}")
            return []

    def is_available(self) -> bool:
        """Vérifie rapidement si Ollama est joignable."""
        try:
            ollama.list()
            return True
        except:
            return False