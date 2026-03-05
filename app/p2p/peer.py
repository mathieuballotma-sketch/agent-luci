"""
Représentation d'un pair dans le réseau P2P.
"""
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class Peer:
    """Informations sur un pair distant."""
    peer_id: str
    host: str
    port: int
    last_seen: float
    public_key: Optional[bytes] = None
    capabilities: list = None  # ex: ["cyber", "compute", "storage"]
    connection = None  # référence à la connexion active (objet websocket ou autre)