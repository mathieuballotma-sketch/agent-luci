"""
Définition des messages échangés entre pairs.
"""
import json
import time
from typing import Dict, Any
import hashlib
import base64

from ..utils.crypto import CryptoManager  # pour signer les messages


class Message:
    """Message signé échangé entre pairs."""

    def __init__(self, msg_type: str, payload: Dict[str, Any], sender_id: str, crypto: CryptoManager):
        self.msg_type = msg_type
        self.payload = payload
        self.sender_id = sender_id
        self.timestamp = time.time()
        self.signature = self._sign(crypto)

    def _sign(self, crypto: CryptoManager) -> str:
        """Signe le message avec la clé privée du nœud."""
        data = f"{self.msg_type}{json.dumps(self.payload)}{self.sender_id}{self.timestamp}"
        signature = crypto.sign(data.encode())
        return base64.b64encode(signature).decode()

    def verify(self, crypto: CryptoManager, public_key: bytes) -> bool:
        """Vérifie la signature avec la clé publique de l'émetteur."""
        data = f"{self.msg_type}{json.dumps(self.payload)}{self.sender_id}{self.timestamp}"
        try:
            crypto.verify(data.encode(), base64.b64decode(self.signature), public_key)
            return True
        except Exception:
            return False

    def to_json(self) -> str:
        return json.dumps({
            "type": self.msg_type,
            "payload": self.payload,
            "sender": self.sender_id,
            "timestamp": self.timestamp,
            "signature": self.signature
        })

    @classmethod
    def from_json(cls, data: str) -> "Message":
        obj = json.loads(data)
        msg = cls.__new__(cls)
        msg.msg_type = obj["type"]
        msg.payload = obj["payload"]
        msg.sender_id = obj["sender"]
        msg.timestamp = obj["timestamp"]
        msg.signature = obj["signature"]
        return msg