"""
Mémoire épisodique : stocke les interactions passées dans une base vectorielle.
Permet de retrouver des souvenirs similaires pour enrichir le contexte.
Utilise ChromaDB avec une politique d'éviction LRU (basée sur timestamp).
Version avec gestion optionnelle de sentence-transformers.
"""

import time
import hashlib
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path

import chromadb
import numpy as np

from ..utils.logger import logger

# Tentative d'import de SentenceTransformer
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers non disponible, la mémoire épisodique utilisera un embedding factice (recherche désactivée).")


class DummyEmbedder:
    """Embedder factice qui retourne un vecteur de zéros."""
    def __init__(self):
        self.dimension = 384  # dimension par défaut

    def encode(self, texts, **kwargs):
        if isinstance(texts, str):
            return np.zeros(self.dimension)
        return np.zeros((len(texts), self.dimension))


class EpisodicMemory:
    """
    Mémoire épisodique à long terme.
    Chaque souvenir contient : query, response, timestamp, metadata (satisfaction, etc.)
    """

    def __init__(self, persist_directory: str = "./data/episodic_memory",
                 collection_name: str = "episodes",
                 embedding_model: str = "all-MiniLM-L6-v2",
                 max_entries: int = 10000):
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        # Choix de l'embedder
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedder = SentenceTransformer(embedding_model)
                self.dimension = self.embedder.get_sentence_embedding_dimension()
                logger.info(f"Embedder {embedding_model} chargé (dim={self.dimension})")
            except Exception as e:
                logger.error(f"Erreur chargement SentenceTransformer: {e}")
                self.embedder = DummyEmbedder()
                self.dimension = self.embedder.dimension
        else:
            self.embedder = DummyEmbedder()
            self.dimension = self.embedder.dimension

        self.max_entries = max_entries

        # Initialisation ChromaDB
        self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        # On utilise un embedding function factice pour Chroma (car on gère les embeddings nous-mêmes)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

        self._lock = threading.RLock()
        logger.info(f"🧠 Mémoire épisodique initialisée avec {self.collection.count()} souvenirs (embedder: {'réel' if SENTENCE_TRANSFORMERS_AVAILABLE else 'factice'})")

    def add(self, query: str, response: str, metadata: Optional[Dict] = None):
        """
        Ajoute une interaction dans la mémoire épisodique.
        Se fait de manière asynchrone (via un thread) pour ne pas bloquer.
        """
        def _add():
            with self._lock:
                # Vérifier si le nombre d'entrées dépasse le max
                current_count = self.collection.count()
                if current_count >= self.max_entries:
                    self._evict_oldest()

                # Générer un ID unique
                doc_id = hashlib.md5(f"{query}_{time.time()}".encode()).hexdigest()

                # Métadonnées par défaut
                meta = metadata or {}
                meta['timestamp'] = time.time()
                meta['query'] = query  # Pour faciliter la recherche

                # Calcul de l'embedding (si embedder réel, sinon vecteur nul)
                embedding = self.embedder.encode(query).tolist()

                # Ajouter à Chroma
                self.collection.add(
                    documents=[response],
                    metadatas=[meta],
                    ids=[doc_id],
                    embeddings=[embedding]
                )
                logger.debug(f"Souvenir ajouté: {query[:50]}...")

        # Lancer dans un thread pour ne pas bloquer
        threading.Thread(target=_add, daemon=True).start()

    def search(self, query: str, n_results: int = 3, min_similarity: float = 0.7) -> List[Dict]:
        """
        Recherche des souvenirs similaires à la requête.
        Retourne une liste de dict avec 'query', 'response', 'metadata', 'similarity'.
        Si l'embedder est factice, retourne une liste vide (pas de recherche possible).
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.debug("Recherche épisodique désactivée (embedder factice)")
            return []

        if self.collection.count() == 0:
            return []

        try:
            # Encoder la requête
            query_embedding = self.embedder.encode(query).tolist()

            # Recherche dans Chroma
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"]
            )

            # Formater les résultats
            memories = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i]
                    distance = results['distances'][0][i]
                    similarity = 1 - distance  # cosine distance -> similarity

                    if similarity >= min_similarity:
                        memories.append({
                            'query': metadata.get('query', ''),
                            'response': doc,
                            'metadata': metadata,
                            'similarity': similarity
                        })

            return memories

        except Exception as e:
            logger.error(f"Erreur lors de la recherche épisodique: {e}")
            return []

    def _evict_oldest(self):
        """Supprime le souvenir le plus ancien (par timestamp)"""
        try:
            # Récupérer tous les métadonnées avec timestamps
            all_data = self.collection.get(include=["metadatas"])
            if not all_data['metadatas']:
                return

            # Trouver l'ID du plus ancien
            oldest_id = None
            oldest_ts = float('inf')
            for i, meta in enumerate(all_data['metadatas']):
                ts = meta.get('timestamp', 0)
                if ts < oldest_ts:
                    oldest_ts = ts
                    oldest_id = all_data['ids'][i]

            if oldest_id:
                self.collection.delete(ids=[oldest_id])
                logger.debug(f"Éviction du souvenir {oldest_id} (timestamp {oldest_ts})")
        except Exception as e:
            logger.error(f"Erreur lors de l'éviction: {e}")

    def get_stats(self) -> dict:
        """Retourne des statistiques sur la mémoire"""
        return {
            'count': self.collection.count(),
            'max_entries': self.max_entries,
        }