"""
Cache de prompts avec support exact et vectoriel (FAISS).
Version optimisée avec cache exact pour les plans.
"""

import hashlib
import pickle
import time
import threading
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any
from collections import OrderedDict

import numpy as np
import faiss

from ..utils.logger import logger
from ..utils.metrics import (
    record_cache_hit, record_cache_miss,
    record_plan_cache_hit, record_plan_cache_miss
)

# Tentative d'import de SentenceTransformer, optionnel
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers non disponible, cache vectoriel désactivé.")


class PromptCache:
    """
    Cache intelligent avec :
    - Cache exact (clé = hash prompt+system+model)
    - Cache exact pour les plans (clé = hash de la requête)
    - Cache vectoriel (FAISS) pour similarité sémantique (si sentence-transformers disponible)
    - Éviction LRU pour les caches exacts
    - Gestion thread-safe
    """

    def __init__(self, cache_dir: Path = Path("./data/cache"), max_size: int = 10000):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = max_size

        # Modèle d'embedding (optionnel)
        self.embedder = None
        self.dimension = 384  # dimension par défaut pour all-MiniLM-L6-v2
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
                self.dimension = self.embedder.get_sentence_embedding_dimension()
            except Exception as e:
                logger.error(f"Erreur chargement SentenceTransformer: {e}")
                self.embedder = None

        # Index FAISS pour les réponses et les plans
        self.index_path = cache_dir / "faiss.index"
        self.metadata_path = cache_dir / "metadata.pkl"
        self._load_index()

        # Cache exact (réponses)
        self.exact_cache: Dict[str, Tuple[str, float, int]] = OrderedDict()
        self.access_count = {}
        self.exact_cache_path = cache_dir / "exact_cache.pkl"
        self._load_exact_cache()

        # Cache exact pour les plans (clé = hash de la requête)
        self.exact_plan_cache: Dict[str, Tuple[List[Dict], float, int]] = OrderedDict()
        self.plan_access_count = {}
        self.exact_plan_cache_path = cache_dir / "exact_plan_cache.pkl"
        self._load_exact_plan_cache()

        # Statistiques
        self.stats = {'hits_exact': 0, 'hits_vector': 0, 'misses': 0, 'evictions': 0,
                      'plan_hits_exact': 0, 'plan_hits_vector': 0, 'plan_misses': 0}

        self._lock = threading.RLock()
        logger.info(f"✅ PromptCache optimisé initialisé ({len(self.exact_cache)} exactes, {len(self.exact_plan_cache)} plans exacts, {self.index.ntotal} vectorielles)")

    # ----------------------------------------------------------------------
    # Gestion de l'index FAISS
    # ----------------------------------------------------------------------
    def _load_index(self):
        if self.index_path.exists():
            self.index = faiss.read_index(str(self.index_path))
        else:
            self.index = faiss.IndexFlatIP(self.dimension)  # Similarité cosinus

        if self.metadata_path.exists():
            with open(self.metadata_path, 'rb') as f:
                self.metadata = pickle.load(f)  # Liste de dicts
        else:
            self.metadata = []

    def _save_index(self):
        with self._lock:
            try:
                faiss.write_index(self.index, str(self.index_path))
                with open(self.metadata_path, 'wb') as f:
                    pickle.dump(self.metadata, f)
            except Exception as e:
                logger.error(f"Erreur sauvegarde index: {e}")

    # ----------------------------------------------------------------------
    # Gestion du cache exact (réponses)
    # ----------------------------------------------------------------------
    def _load_exact_cache(self):
        if self.exact_cache_path.exists():
            try:
                with open(self.exact_cache_path, 'rb') as f:
                    data = pickle.load(f)
                    for key, (resp, ts, acc) in data.items():
                        self.exact_cache[key] = (resp, ts, acc)
                        self.access_count[key] = acc
            except Exception as e:
                logger.error(f"Erreur chargement cache exact: {e}")

    def _save_exact_cache(self):
        with self._lock:
            try:
                with open(self.exact_cache_path, 'wb') as f:
                    pickle.dump(dict(self.exact_cache), f)
            except Exception as e:
                logger.error(f"Erreur sauvegarde cache exact: {e}")

    # ----------------------------------------------------------------------
    # Gestion du cache exact pour les plans
    # ----------------------------------------------------------------------
    def _load_exact_plan_cache(self):
        if self.exact_plan_cache_path.exists():
            try:
                with open(self.exact_plan_cache_path, 'rb') as f:
                    data = pickle.load(f)
                    for key, (plan, ts, acc) in data.items():
                        self.exact_plan_cache[key] = (plan, ts, acc)
                        self.plan_access_count[key] = acc
            except Exception as e:
                logger.error(f"Erreur chargement cache exact plans: {e}")

    def _save_exact_plan_cache(self):
        with self._lock:
            try:
                with open(self.exact_plan_cache_path, 'wb') as f:
                    pickle.dump(dict(self.exact_plan_cache), f)
            except Exception as e:
                logger.error(f"Erreur sauvegarde cache exact plans: {e}")

    def _evict_if_needed(self):
        """Éviction LRU pour le cache exact des réponses."""
        with self._lock:
            if len(self.exact_cache) <= self.max_size:
                return
            sorted_keys = sorted(self.access_count.keys(), key=lambda k: self.access_count[k])
            to_remove = len(self.exact_cache) - self.max_size
            for key in sorted_keys[:to_remove]:
                if key in self.exact_cache:
                    del self.exact_cache[key]
                if key in self.access_count:
                    del self.access_count[key]
                self.stats['evictions'] += 1
            logger.debug(f"🧹 Éviction de {to_remove} entrées de cache exact")

    def _evict_plan_if_needed(self):
        """Éviction LRU pour le cache exact des plans."""
        with self._lock:
            if len(self.exact_plan_cache) <= self.max_size:
                return
            sorted_keys = sorted(self.plan_access_count.keys(), key=lambda k: self.plan_access_count[k])
            to_remove = len(self.exact_plan_cache) - self.max_size
            for key in sorted_keys[:to_remove]:
                if key in self.exact_plan_cache:
                    del self.exact_plan_cache[key]
                if key in self.plan_access_count:
                    del self.plan_access_count[key]
                self.stats['evictions'] += 1
            logger.debug(f"🧹 Éviction de {to_remove} plans exacts")

    def _get_exact_key(self, prompt: str, system: str, model: str) -> str:
        key = f"{prompt}||{system}||{model}"
        return hashlib.md5(key.encode()).hexdigest()

    # ----------------------------------------------------------------------
    # API publique pour les réponses
    # ----------------------------------------------------------------------
    def get(self, prompt: str, system: str = "", model: str = "auto", similarity_threshold: float = 0.95) -> Optional[str]:
        exact_key = self._get_exact_key(prompt, system, model)
        with self._lock:
            if exact_key in self.exact_cache:
                response, timestamp, acc = self.exact_cache[exact_key]
                self.access_count[exact_key] = acc + 1
                self.stats['hits_exact'] += 1
                record_cache_hit("exact")
                logger.debug(f"🎯 Cache exact trouvé")
                return response

        # Si le cache vectoriel n'est pas disponible, on s'arrête là
        if not SENTENCE_TRANSFORMERS_AVAILABLE or self.embedder is None:
            self.stats['misses'] += 1
            record_cache_miss("vector")
            return None

        if self.index.ntotal == 0:
            self.stats['misses'] += 1
            record_cache_miss("vector")
            return None

        query_embedding = self.embedder.encode([prompt]).astype('float32')
        scores, indices = self.index.search(query_embedding, k=3)
        if scores[0][0] > similarity_threshold:
            meta_idx = indices[0][0]
            if 0 <= meta_idx < len(self.metadata):
                entry = self.metadata[meta_idx]
                if entry.get('type') == 'response' and (model == 'auto' or entry.get('model') == model):
                    cached_response = entry['response']
                    self.stats['hits_vector'] += 1
                    record_cache_hit("vector")
                    logger.debug(f"🎯 Cache vectoriel trouvé (score: {scores[0][0]:.3f})")
                    self.put(prompt, system, model, cached_response, from_vector=True)
                    return cached_response

        self.stats['misses'] += 1
        record_cache_miss("vector")
        return None

    def put(self, prompt: str, system: str, model: str, response: str, from_vector: bool = False):
        with self._lock:
            exact_key = self._get_exact_key(prompt, system, model)
            self.exact_cache[exact_key] = (response, time.time(), 1)
            self.access_count[exact_key] = 1
            self._evict_if_needed()

            if not from_vector and SENTENCE_TRANSFORMERS_AVAILABLE and self.embedder is not None:
                embedding = self.embedder.encode([prompt]).astype('float32')
                self.index.add(embedding)
                self.metadata.append({
                    'prompt': prompt,
                    'response': response,
                    'model': model,
                    'timestamp': time.time(),
                    'type': 'response'
                })

            if len(self.metadata) % 100 == 0:
                self._save_index()
                self._save_exact_cache()

    # ----------------------------------------------------------------------
    # API pour les plans d'actions
    # ----------------------------------------------------------------------
    def get_plan(self, query: str, similarity_threshold: float = 0.75) -> Optional[List[Dict[str, Any]]]:
        # D'abord, vérifier le cache exact
        exact_key = hashlib.md5(query.encode()).hexdigest()
        with self._lock:
            if exact_key in self.exact_plan_cache:
                plan, timestamp, acc = self.exact_plan_cache[exact_key]
                self.plan_access_count[exact_key] = acc + 1
                self.stats['plan_hits_exact'] += 1
                record_plan_cache_hit()
                logger.debug(f"📋 Plan exact trouvé")
                return plan

        if not SENTENCE_TRANSFORMERS_AVAILABLE or self.embedder is None or self.index.ntotal == 0:
            self.stats['plan_misses'] += 1
            record_plan_cache_miss()
            return None

        query_embedding = self.embedder.encode([query]).astype('float32')
        scores, indices = self.index.search(query_embedding, k=5)
        if scores[0][0] < similarity_threshold:
            self.stats['plan_misses'] += 1
            record_plan_cache_miss()
            return None

        for i, score in enumerate(scores[0]):
            if score < similarity_threshold:
                break
            meta_idx = indices[0][i]
            if 0 <= meta_idx < len(self.metadata):
                entry = self.metadata[meta_idx]
                if entry.get('type') == 'plan':
                    plan = entry['plan']
                    # Mettre en cache exact
                    self.put_plan(query, plan, from_vector=True)
                    self.stats['plan_hits_vector'] += 1
                    record_plan_cache_hit()
                    logger.debug(f"📋 Plan vectoriel trouvé (score: {score:.3f})")
                    return plan
        self.stats['plan_misses'] += 1
        record_plan_cache_miss()
        return None

    def put_plan(self, query: str, plan: List[Dict[str, Any]], from_vector: bool = False):
        with self._lock:
            exact_key = hashlib.md5(query.encode()).hexdigest()
            self.exact_plan_cache[exact_key] = (plan, time.time(), 1)
            self.plan_access_count[exact_key] = 1
            self._evict_plan_if_needed()

            if not from_vector and SENTENCE_TRANSFORMERS_AVAILABLE and self.embedder is not None:
                embedding = self.embedder.encode([query]).astype('float32')
                self.index.add(embedding)
                self.metadata.append({
                    'prompt': query,
                    'plan': plan,
                    'timestamp': time.time(),
                    'type': 'plan'
                })
                if len(self.metadata) % 100 == 0:
                    self._save_index()
                    self._save_exact_plan_cache()
            logger.debug(f"📌 Plan mis en cache pour: {query[:50]}...")

    # ----------------------------------------------------------------------
    # Utilitaires
    # ----------------------------------------------------------------------
    def clear_old(self, max_age_hours: int = 24):
        with self._lock:
            now = time.time()
            to_delete = []
            for key, (_, ts, _) in self.exact_cache.items():
                if now - ts > max_age_hours * 3600:
                    to_delete.append(key)
            for key in to_delete:
                del self.exact_cache[key]
                if key in self.access_count:
                    del self.access_count[key]
            if to_delete:
                self._save_exact_cache()
                logger.info(f"🧹 {len(to_delete)} entrées exactes expirées supprimées")

    def get_stats(self) -> dict:
        total = self.stats['hits_exact'] + self.stats['hits_vector'] + self.stats['misses']
        hit_rate = (self.stats['hits_exact'] + self.stats['hits_vector']) / total * 100 if total else 0
        plan_total = self.stats['plan_hits_exact'] + self.stats['plan_hits_vector'] + self.stats['plan_misses']
        plan_hit_rate = (self.stats['plan_hits_exact'] + self.stats['plan_hits_vector']) / plan_total * 100 if plan_total else 0
        return {
            **self.stats,
            'hit_rate': f"{hit_rate:.1f}%",
            'plan_hit_rate': f"{plan_hit_rate:.1f}%",
            'exact_entries': len(self.exact_cache),
            'exact_plan_entries': len(self.exact_plan_cache),
            'vector_entries': len(self.metadata),
            'total_requests': total
        }