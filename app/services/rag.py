"""
Service de RAG (Retrieval-Augmented Generation) utilisant FAISS pour la recherche
et SQLite pour stocker les métadonnées des chunks.
Version avec gestion optionnelle de sentence-transformers.
"""

import os
import hashlib
import pickle
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Generator
import pymupdf  # fitz
import faiss
import numpy as np
from ..utils.logger import get_logger
from ..utils.exceptions import RAGError, IndexingError

# Tentative d'import de SentenceTransformer
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    get_logger(__name__).warning("sentence-transformers non disponible, le RAG sera désactivé.")

logger = get_logger(__name__)


class DummyEmbedder:
    """Embedder factice qui retourne un vecteur de zéros."""
    def __init__(self, dimension=384):
        self.dimension = dimension

    def encode(self, texts, show_progress_bar=False, **kwargs):
        if isinstance(texts, str):
            return np.zeros(self.dimension)
        return np.zeros((len(texts), self.dimension))


class RAGService:
    """
    Service de RAG utilisant FAISS et SQLite.
    Si sentence-transformers n'est pas disponible, le service sera inactif.
    """

    def __init__(self, config):
        self.config = config
        self.data_dir = Path("./rag_data")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Modèle d'embedding (optionnel)
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedder = SentenceTransformer(config.embedding_model)
                self.dimension = self.embedder.get_sentence_embedding_dimension()
                logger.info(f"Embedder {config.embedding_model} chargé (dim={self.dimension})")
            except Exception as e:
                logger.error(f"Erreur chargement SentenceTransformer: {e}")
                self.embedder = DummyEmbedder()
                self.dimension = self.embedder.dimension
        else:
            self.embedder = DummyEmbedder()
            self.dimension = self.embedder.dimension
            logger.info("RAG désactivé (sentence-transformers manquant)")

        # Paramètres
        self.chunk_size = config.chunk_size
        self.chunk_overlap = config.chunk_overlap
        self.max_sources = config.max_sources

        # Initialisation FAISS
        self._init_faiss()

        # Initialisation SQLite
        self._init_sqlite()

        logger.info(f"✅ RAG initialisé avec FAISS (dim={self.dimension})")

    def _init_faiss(self):
        self.index_path = self.data_dir / "faiss.index"
        if self.index_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            logger.info(f"Index FAISS chargé ({self.index.ntotal} vecteurs)")
        else:
            self.index = faiss.IndexFlatL2(self.dimension)
            logger.info("Nouvel index FAISS créé")

        # Mapping entre les positions FAISS et les IDs des chunks
        self.mapping_path = self.data_dir / "id_mapping.pkl"
        if self.mapping_path.exists():
            with open(self.mapping_path, "rb") as f:
                self.id_mapping = pickle.load(f)
        else:
            self.id_mapping = []

    def _init_sqlite(self):
        self.db_path = self.data_dir / "metadata.db"
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL,
                hash TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)")
        self.conn.commit()

    def _get_file_hash(self, path: Path) -> str:
        hasher = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _chunk_text(self, text: str) -> List[str]:
        words = text.split()
        if len(words) <= self.chunk_size:
            return [text]
        step = self.chunk_size - self.chunk_overlap
        chunks = []
        for i in range(0, len(words), step):
            chunk = ' '.join(words[i:i + self.chunk_size])
            chunks.append(chunk)
        return chunks

    def _read_pdf(self, path: Path) -> str:
        try:
            doc = pymupdf.open(path)
            text = ""
            for page in doc:
                text += page.get_text()
            return text
        except Exception as e:
            raise IndexingError(f"Erreur lecture PDF {path}: {e}")

    def _read_text(self, path: Path) -> str:
        encodings = ['utf-8', 'latin-1', 'cp1252']
        for enc in encodings:
            try:
                with open(path, 'r', encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise IndexingError(f"Impossible de lire le fichier {path} avec les encodages essayés")

    def index_file(self, path: str) -> bool:
        """
        Indexe un fichier (PDF ou texte) dans la base RAG.
        Si l'embedder est factice, ne fait rien et retourne False.
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.warning("Indexation désactivée : sentence-transformers manquant")
            return False

        path = Path(path)
        if not path.exists():
            raise IndexingError(f"Fichier introuvable: {path}")

        file_hash = self._get_file_hash(path)

        # Vérifier si le fichier est déjà indexé avec le même hash
        cur = self.conn.execute(
            "SELECT id FROM chunks WHERE source=? AND hash=? LIMIT 1",
            (str(path), file_hash)
        )
        if cur.fetchone():
            logger.info(f"Fichier déjà indexé et inchangé: {path}")
            return True

        # Supprimer les anciennes entrées pour ce fichier (si elles existent)
        self.conn.execute("DELETE FROM chunks WHERE source=?", (str(path),))
        self.conn.commit()

        # Lire le contenu
        if path.suffix.lower() == '.pdf':
            text = self._read_pdf(path)
        else:
            text = self._read_text(path)

        if not text.strip():
            logger.warning(f"Fichier vide ou illisible: {path}")
            return False

        # Découpage
        chunks = self._chunk_text(text)

        # Calcul des embeddings en batch pour performance
        try:
            embeddings = self.embedder.encode(chunks, show_progress_bar=False)
        except Exception as e:
            raise IndexingError(f"Erreur lors du calcul des embeddings: {e}")

        # Insertion dans SQLite et FAISS
        cur = self.conn.cursor()
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            cur.execute("""
                INSERT INTO chunks (source, chunk_index, total_chunks, hash, content)
                VALUES (?, ?, ?, ?, ?)
            """, (str(path), i, len(chunks), file_hash, chunk))
            chunk_id = cur.lastrowid
            # Ajouter à FAISS
            self.index.add(np.array([emb]).astype('float32'))
            self.id_mapping.append(chunk_id)

        self.conn.commit()

        # Sauvegarder l'index et le mapping
        faiss.write_index(self.index, str(self.index_path))
        with open(self.mapping_path, "wb") as f:
            pickle.dump(self.id_mapping, f)

        logger.info(f"✅ Indexé: {path} ({len(chunks)} chunks)")
        return True

    def index_folder(self, path: str) -> int:
        """
        Indexe récursivement tous les fichiers supportés dans un dossier.
        Si l'embedder est factice, retourne 0.
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.warning("Indexation de dossier désactivée : sentence-transformers manquant")
            return 0

        path = Path(path)
        if not path.is_dir():
            raise IndexingError(f"Dossier invalide: {path}")

        extensions = {'.pdf', '.txt', '.md', '.py', '.rst', '.csv', '.json', '.xml'}
        count = 0
        for file_path in path.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in extensions:
                try:
                    if self.index_file(str(file_path)):
                        count += 1
                except Exception as e:
                    logger.error(f"Erreur lors de l'indexation de {file_path}: {e}")
        logger.info(f"✅ {count} fichiers indexés dans {path}")
        return count

    def query(self, question: str, n_results: Optional[int] = None) -> str:
        """
        Recherche les chunks les plus pertinents pour une question.
        Si l'embedder est factice, retourne une chaîne vide.
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.debug("RAG désactivé : retourne chaîne vide")
            return ""

        if n_results is None:
            n_results = self.max_sources

        if self.index.ntotal == 0:
            logger.debug("Index FAISS vide")
            return ""

        try:
            q_emb = self.embedder.encode([question]).astype('float32')
        except Exception as e:
            logger.error(f"Erreur d'encodage: {e}")
            return ""

        distances, indices = self.index.search(q_emb, n_results)

        if indices[0][0] == -1:
            return ""

        context_parts = []
        for idx in indices[0]:
            if idx == -1 or idx >= len(self.id_mapping):
                continue
            chunk_id = self.id_mapping[idx]
            cur = self.conn.execute("""
                SELECT content, source, chunk_index, total_chunks
                FROM chunks WHERE id=?
            """, (chunk_id,))
            row = cur.fetchone()
            if row:
                content, source, chunk_idx, total = row
                source_name = Path(source).name
                context_parts.append(
                    f"[Source: {source_name} - Chunk {chunk_idx+1}/{total}]\n{content}"
                )

        return "\n\n".join(context_parts)

    def clear(self, source: Optional[str] = None):
        """
        Supprime tous les index ou seulement ceux d'une source spécifique.
        """
        if source:
            cur = self.conn.execute("SELECT id FROM chunks WHERE source=?", (source,))
            ids_to_remove = [row[0] for row in cur.fetchall()]
            if ids_to_remove:
                self.conn.execute("DELETE FROM chunks WHERE source=?", (source,))
                self.conn.commit()
                self._rebuild_faiss()
                logger.info(f"Index supprimé pour {source}")
        else:
            self.conn.execute("DELETE FROM chunks")
            self.conn.commit()
            self.index = faiss.IndexFlatL2(self.dimension)
            self.id_mapping = []
            faiss.write_index(self.index, str(self.index_path))
            with open(self.mapping_path, "wb") as f:
                pickle.dump([], f)
            logger.info("Tous les index supprimés")

    def _rebuild_faiss(self):
        cur = self.conn.execute("SELECT id, content FROM chunks ORDER BY id")
        rows = cur.fetchall()
        if not rows:
            self.index = faiss.IndexFlatL2(self.dimension)
            self.id_mapping = []
        else:
            contents = [row[1] for row in rows]
            ids = [row[0] for row in rows]
            logger.info(f"Reconstruction de l'index FAISS avec {len(contents)} chunks...")
            embeddings = self.embedder.encode(contents, show_progress_bar=True)
            self.index = faiss.IndexFlatL2(self.dimension)
            self.index.add(embeddings.astype('float32'))
            self.id_mapping = ids
        faiss.write_index(self.index, str(self.index_path))
        with open(self.mapping_path, "wb") as f:
            pickle.dump(self.id_mapping, f)