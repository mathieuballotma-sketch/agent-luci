"""
Agent Profile - Analyse le profil utilisateur pour personnaliser l'interaction.
Utilise la mémoire épisodique et les documents indexés pour extraire :
- Vocabulaire signature (mots fréquents, expressions uniques)
- Thèmes récurrents (clusters sémantiques)
- Pics d'activité (moments productifs)
- Objectifs de vie (déduits des notes)
"""

import time
import threading
import numpy as np
from collections import Counter
from sklearn.cluster import KMeans
from typing import List, Dict, Any, Optional

from app.agents.base_agent import BaseAgent
from app.memory import MemoryService
from app.services.rag import RAGService
from app.utils.logger import logger


class ProfileAgent(BaseAgent):
    """
    Agent dédié à l'analyse du profil utilisateur.
    Il n'est pas appelé directement par l'utilisateur, mais tourne en arrière-plan
    pour mettre à jour le profil régulièrement.
    """

    def __init__(self, llm_service, bus, memory_service: MemoryService, rag_service: RAGService, config: dict):
        super().__init__("ProfileAgent", llm_service, bus)
        self.memory = memory_service
        self.rag = rag_service
        self.config = config

        self.profile = {
            "vocabulary": {},
            "themes": [],
            "activity_peaks": [],
            "goals": [],
            "last_updated": 0
        }

        self._lock = threading.RLock()
        self._update_interval = config.get("profile_update_interval", 3600)
        self._stop_event = threading.Event()
        self._thread = None

        logger.info("👤 ProfileAgent initialisé")

    def start(self):
        if self._thread is None:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._update_loop, daemon=True)
            self._thread.start()
            logger.info("🔄 ProfileAgent: mise à jour périodique activée")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _update_loop(self):
        while not self._stop_event.is_set():
            try:
                self.update_profile()
            except Exception as e:
                logger.error(f"Erreur dans la mise à jour du profil: {e}")
            time.sleep(self._update_interval)

    def update_profile(self):
        with self._lock:
            logger.info("👤 Mise à jour du profil utilisateur...")

            # Pour l'instant, on n'a pas de méthode get_recent_episodes dans MemoryService.
            # On utilise un échantillon vide, mais on pourra améliorer plus tard.
            interactions = []

            vocab = self._extract_vocabulary(interactions)
            self.profile["vocabulary"] = vocab

            themes = self._extract_themes(interactions)
            self.profile["themes"] = themes

            peaks = self._analyze_activity_peaks()
            self.profile["activity_peaks"] = peaks

            goals = self._infer_goals()
            self.profile["goals"] = goals

            self.profile["last_updated"] = time.time()
            logger.info("✅ Profil utilisateur mis à jour")

    def _extract_vocabulary(self, interactions: List[Dict]) -> Dict:
        """Analyse les textes pour trouver les mots et expressions caractéristiques."""
        texts = []
        for item in interactions:
            texts.append(item.get('query', ''))
            texts.append(item.get('response', ''))
        full_text = ' '.join(texts).lower()

        words = full_text.split()
        word_counts = Counter(words)

        # Stopwords basiques
        common_words = {'le', 'la', 'les', 'de', 'du', 'et', 'un', 'une', 'des', 'pour', 'dans',
                        'ce', 'cet', 'cette', 'ces', 'mon', 'ton', 'son', 'notre', 'votre', 'leur',
                        'je', 'tu', 'il', 'elle', 'nous', 'vous', 'ils', 'elles', 'qui', 'que',
                        'quoi', 'dont', 'où', 'comment', 'pourquoi', 'est', 'sont', 'ai', 'as',
                        'a', 'avons', 'avez', 'ont', 'être', 'avoir', 'faire', 'dire', 'voir',
                        'savoir', 'pouvoir', 'vouloir', 'mais', 'ou', 'donc', 'car', 'ni', 'or'}

        # Filtrer les mots
        filtered = {}
        for word, count in word_counts.items():
            if word not in common_words and len(word) > 2:
                filtered[word] = count

        significant_words = Counter(filtered).most_common(20)

        # Bigrammes
        bigrams = [' '.join(words[i:i+2]) for i in range(len(words)-1)]
        bigram_counts = Counter(bigrams)
        filtered_bigrams = {}
        for bigram, count in bigram_counts.items():
            if count > 1 and len(bigram) > 5:
                filtered_bigrams[bigram] = count
        significant_bigrams = Counter(filtered_bigrams).most_common(10)

        return {
            "words": significant_words,
            "bigrams": significant_bigrams
        }

    def _extract_themes(self, interactions: List[Dict]) -> List[Dict]:
        queries = [item['query'] for item in interactions if 'query' in item]
        if len(queries) < 10:
            return []

        embeddings = []
        for q in queries:
            emb = self.memory.episodic.embedder.encode(q)
            embeddings.append(emb)
        X = np.array(embeddings)

        n_clusters = min(5, len(queries) // 5)
        if n_clusters < 2:
            return []
        kmeans = KMeans(n_clusters=n_clusters, random_state=0, n_init='auto')
        labels = kmeans.fit_predict(X)

        themes = []
        for i in range(n_clusters):
            indices = np.where(labels == i)[0]
            if len(indices) == 0:
                continue
            cluster_queries = [queries[idx] for idx in indices]
            words = ' '.join(cluster_queries).lower().split()
            word_counts = Counter(words)
            common = [w for w, c in word_counts.most_common(5) if len(w) > 3]
            themes.append({
                "id": i,
                "keywords": common,
                "count": len(indices),
                "sample_queries": cluster_queries[:3]
            })
        return themes

    def _analyze_activity_peaks(self) -> List[int]:
        # À implémenter avec les timestamps des souvenirs
        return []

    def _infer_goals(self) -> List[str]:
        recent = self.memory.working.get_recent(n=10)
        recent_queries = [item['query'] for item in recent if 'query' in item]
        if not recent_queries:
            return []

        prompt = f"""
        Voici une liste des dernières requêtes de l'utilisateur :
        {chr(10).join(recent_queries)}

        Quels semblent être ses objectifs de vie ou ses projets principaux ?
        Liste 3 objectifs maximum, de manière concise, sous forme de phrases courtes.
        """
        try:
            response = self.ask_llm(prompt, model="balanced")
            goals = [line.strip('- ') for line in response.split('\n') if line.strip()]
            return goals[:3]
        except Exception as e:
            logger.error(f"Erreur lors de l'inférence des objectifs: {e}")
            return []

    def get_profile(self) -> Dict:
        with self._lock:
            return self.profile.copy()

    def can_handle(self, query: str) -> bool:
        return False

    def handle(self, query: str) -> str:
        return "Cet agent n'est pas destiné à être utilisé directement."