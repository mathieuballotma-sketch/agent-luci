"""
Serveur P2P asynchrone avec TLS.
"""

import asyncio
import json
import ssl
from typing import Callable, Optional

from app.utils.logger import logger


class P2PServer:
    def __init__(self, host: str, port: int, certfile: str, keyfile: str, message_handler: Callable):
        self.host = host
        self.port = port
        self.certfile = certfile
        self.keyfile = keyfile
        self.message_handler = message_handler
        self.server = None
        self.ssl_context = self._create_ssl_context()

    def _create_ssl_context(self):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(self.certfile, self.keyfile)
        return context

    async def start(self):
        self.server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            ssl=self.ssl_context
        )
        logger.info(f"🖥️ Serveur P2P démarré sur {self.host}:{self.port}")

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("Serveur P2P arrêté")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        logger.debug(f"Connexion entrante de {peer}")
        try:
            data = await reader.read(4096)
            if data:
                message = json.loads(data.decode())
                # Appeler le handler avec le message et l'adresse du pair
                await self.message_handler(message, peer, writer)
        except Exception as e:
            logger.error(f"Erreur avec le client {peer}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()