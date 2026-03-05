"""
Client P2P asynchrone avec TLS.
"""

import asyncio
import json
import ssl
from typing import Dict, Any, Optional

from app.utils.logger import logger


class P2PClient:
    def __init__(self, certfile: str):
        self.certfile = certfile
        self.ssl_context = self._create_ssl_context()

    def _create_ssl_context(self):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations(self.certfile)
        # Désactiver la vérification du hostname pour les tests, mais en prod il faudrait l'activer
        context.check_hostname = False
        return context

    async def send_message(self, host: str, port: int, message: Dict[str, Any]) -> Optional[Dict]:
        """Envoie un message à un pair et attend une réponse (optionnelle)."""
        try:
            reader, writer = await asyncio.open_connection(
                host, port, ssl=self.ssl_context
            )
            data = json.dumps(message).encode()
            writer.write(data)
            await writer.drain()

            # Lire la réponse (si attendue)
            response_data = await reader.read(4096)
            response = json.loads(response_data.decode()) if response_data else None

            writer.close()
            await writer.wait_closed()
            return response
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi à {host}:{port} : {e}")
            return None