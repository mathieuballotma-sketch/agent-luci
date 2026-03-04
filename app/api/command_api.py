# app/api/command_api.py
"""
API REST pour envoyer des commandes à Agent Lucide.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn
import threading

from ..core.engine import LucidEngine


class CommandRequest(BaseModel):
    query: str
    use_rag: Optional[bool] = True


class CommandResponse(BaseModel):
    response: str
    latency: float


class CommandAPI:
    """
    Wrapper pour l'API FastAPI, lié à une instance de moteur.
    """

    def __init__(self, engine: LucidEngine, host: str = "0.0.0.0", port: int = 8001):
        self.engine = engine
        self.host = host
        self.port = port
        self.app = FastAPI(title="Agent Lucide Command API")
        self._setup_routes()

    def _setup_routes(self):
        @self.app.post("/command", response_model=CommandResponse)
        async def command(request: CommandRequest):
            """
            Reçoit une commande textuelle, la traite et retourne la réponse.
            """
            try:
                response, latency = await self.engine.process_async(
                    request.query, use_rag=request.use_rag
                )
                return CommandResponse(response=response, latency=latency)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/health")
        async def health():
            return {"status": "ok"}

    def start(self):
        """Démarre le serveur API dans un thread séparé."""
        def run():
            uvicorn.run(self.app, host=self.host, port=self.port)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        print(f"✅ API commande démarrée sur http://{self.host}:{self.port}")