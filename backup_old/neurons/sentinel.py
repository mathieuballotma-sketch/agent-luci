# app/brain/neurons/sentinel.py
import hashlib
from typing import Tuple
from ...providers.manager import ProviderManager
from ...utils.logger import logger

class Sentinel:
    """
    Vérificateur anti-hallucination.
    Utilise un petit modèle (ex: qwen2.5:0.5b) pour valider la cohérence.
    """

    def __init__(self, manager: ProviderManager):
        self.manager = manager
        self._cache = {}  # cache MD5 -> (is_valid, correction)

    def _make_cache_key(self, query: str, response: str) -> str:
        """Génère une clé de cache basée sur le hash de la requête et de la réponse."""
        combined = f"{query}||{response}"
        return hashlib.md5(combined.encode()).hexdigest()

    def should_verify(self, query: str) -> bool:
        """Décide si une requête mérite une vérification (par ex. si elle est longue ou contient des faits)."""
        # Pour l'instant, on vérifie toujours les réponses de plus de 100 caractères
        return len(query) > 100

    def verify(self, response: str, context: str, query: str) -> Tuple[bool, str]:
        """
        Vérifie la réponse.
        Retourne (is_valid, correction) où correction est une réponse corrigée si invalide,
        sinon la réponse originale.
        """
        if not self.should_verify(query):
            return True, response

        cache_key = self._make_cache_key(query, response)
        if cache_key in self._cache:
            logger.debug("Résultat de vérification en cache")
            return self._cache[cache_key]

        # Prompt de vérification
        system = """Tu es un vérificateur de faits. Ta tâche est de détecter les hallucinations dans la réponse donnée.
        Si la réponse contient des informations non étayées par le contexte ou des incohérences, tu dois signaler l'erreur et proposer une correction.
        Réponds UNIQUEMENT au format suivant, sans texte additionnel :
        VALIDE: [oui/non]
        CORRECTION: [si non, la réponse corrigée ; si oui, vide]"""

        user = f"Contexte : {context}\n\nQuestion : {query}\n\nRéponse à vérifier : {response}"

        try:
            # On utilise le modèle sentinel (type "sentinel" dans le manager)
            verification = self.manager.generate(
                query=user,
                system=system,
                priority="sentinel"  # Supposons que le manager a un type "sentinel"
            )
        except Exception as e:
            logger.error(f"Échec de la vérification : {e}")
            # En cas d'erreur, on considère que c'est valide pour ne pas bloquer
            return True, response

        # Parsing de la réponse
        is_valid = False
        correction = response
        for line in verification.split('\n'):
            if line.startswith("VALIDE:"):
                is_valid = "oui" in line.lower()
            elif line.startswith("CORRECTION:"):
                correction = line.replace("CORRECTION:", "").strip() 

        result = (is_valid, correction if not is_valid else response)
        self._cache[cache_key] = result
        logger.debug(f"Vérification : {'valide' if is_valid else 'invalide'}")
        return result