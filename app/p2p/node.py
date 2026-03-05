"""
Nœud P2P simplifié avec serveur et client TLS.
Gère la liste des pairs, la découverte, la diffusion.
"""

import asyncio
import threading
import time
import json
from typing import Dict, List, Optional, Set, Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.logger import logger
from app.utils.crypto import CryptoManager
from .server import P2PServer
from .client import P2PClient


@dataclass
class Peer:
    """Représente un pair du réseau."""
    peer_id: str
    host: str
    port: int
    last_seen: float
    reputation: float = 1.0


class P2PNode:
    def __init__(self, config: dict, crypto: CryptoManager, event_bus, data_dir: Path):
        self.config = config
        self.crypto = crypto
        self.event_bus = event_bus
        self.data_dir = data_dir
        self.enabled = config.get("enabled", False)
        self.port = config.get("port", 9000)
        self.host = config.get("host", "0.0.0.0")
        self.bootstrap_peers = config.get("bootstrap_peers", [])
        self.certfile = str(data_dir / "cert.pem")
        self.keyfile = str(data_dir / "key.pem")

        # Générer ou charger l'identifiant unique du nœud
        self.node_id = self._get_or_create_node_id()

        self.server: Optional[P2PServer] = None
        self.client = P2PClient(self.certfile)
        self.peers: Dict[str, Peer] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        logger.info(f"🔑 Nœud P2P initialisé avec ID: {self.node_id}")

    def _get_or_create_node_id(self) -> str:
        """Récupère ou génère un identifiant unique pour ce nœud."""
        key = "p2p_node_id"
        stored = self.crypto.get(key)
        if stored:
            return stored.decode()
        else:
            import uuid
            new_id = str(uuid.uuid4())[:8]
            self.crypto.store(key, new_id.encode())
            return new_id

    async def start(self):
        if not self.enabled:
            logger.info("P2P désactivé")
            return
        if self._running:
            return
        self._running = True

        # Démarrer le serveur
        self.server = P2PServer(
            host=self.host,
            port=self.port,
            certfile=self.certfile,
            keyfile=self.keyfile,
            message_handler=self._handle_message
        )
        await self.server.start()

        # Se connecter aux pairs d'amorçage
        for peer_str in self.bootstrap_peers:
            await self._connect_to_bootstrap(peer_str)

        # Lancer la boucle de maintenance
        asyncio.create_task(self._maintenance_loop())

        logger.info("🌐 Nœud P2P démarré")

    async def stop(self):
        self._running = False
        if self.server:
            await self.server.stop()
        logger.info("Nœud P2P arrêté")

    async def _connect_to_bootstrap(self, peer_str: str):
        """Connecte à un pair d'amorçage (format host:port)."""
        try:
            host, port_str = peer_str.split(":")
            port = int(port_str)
            # Envoyer un message d'identification
            msg = {
                "type": "ident",
                "node_id": self.node_id,
                "timestamp": time.time()
            }
            response = await self.client.send_message(host, port, msg)
            if response and response.get("type") == "ident_ack":
                peer_id = response.get("node_id")
                if peer_id:
                    with self._lock:
                        self.peers[peer_id] = Peer(
                            peer_id=peer_id,
                            host=host,
                            port=port,
                            last_seen=time.time()
                        )
                    logger.info(f"✅ Connecté au pair {peer_id} ({host}:{port})")
        except Exception as e:
            logger.error(f"Échec de connexion au bootstrap {peer_str}: {e}")

    async def _handle_message(self, message: dict, peer_addr: tuple, writer: asyncio.StreamWriter):
        """Gère les messages entrants."""
        msg_type = message.get("type")
        logger.debug(f"Message reçu de {peer_addr}: {msg_type}")

        if msg_type == "ident":
            # Répondre avec notre identité
            response = {
                "type": "ident_ack",
                "node_id": self.node_id,
                "timestamp": time.time()
            }
            writer.write(json.dumps(response).encode())
            await writer.drain()
            # Ajouter le pair à la liste
            peer_id = message.get("node_id")
            if peer_id:
                host, port = peer_addr
                with self._lock:
                    self.peers[peer_id] = Peer(
                        peer_id=peer_id,
                        host=host,
                        port=port,
                        last_seen=time.time()
                    )
                logger.info(f"✅ Nouveau pair {peer_id} ({host}:{port})")

        elif msg_type == "threat":
            # Relayer la menace à l'agent cyber via le bus
            signature = message.get("signature", {})
            await self.event_bus.publish("network.threat", signature, "p2p")
            logger.info(f"📡 Menace reçue du réseau")

        elif msg_type == "ping":
            # Répondre pong
            response = {"type": "pong", "timestamp": time.time()}
            writer.write(json.dumps(response).encode())
            await writer.drain()

        else:
            logger.warning(f"Type de message inconnu: {msg_type}")

    async def broadcast_threat(self, signature: dict):
        """Diffuse une signature de menace à tous les pairs connectés."""
        msg = {
            "type": "threat",
            "signature": signature,
            "sender": self.node_id,
            "timestamp": time.time()
        }
        with self._lock:
            peers = list(self.peers.values())
        for peer in peers:
            await self.client.send_message(peer.host, peer.port, msg)
        logger.info(f"📢 Menace diffusée à {len(peers)} pairs")

    async def _maintenance_loop(self):
        """Boucle de maintenance : ping périodique, nettoyage des pairs morts."""
        while self._running:
            await asyncio.sleep(60)
            now = time.time()
            with self._lock:
                # Nettoyer les pairs silencieux depuis > 10 minutes
                to_remove = []
                for peer_id, peer in self.peers.items():
                    if now - peer.last_seen > 600:
                        to_remove.append(peer_id)
                for peer_id in to_remove:
                    del self.peers[peer_id]
                if to_remove:
                    logger.debug(f"Nettoyage de {len(to_remove)} pairs inactifs")

    def run_in_thread(self):
        """Lance le nœud dans un thread séparé."""
        if not self.enabled:
            return
        def _run():
            asyncio.run(self.start())
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        logger.info("🧵 Thread P2P démarré")