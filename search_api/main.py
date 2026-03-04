from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import time
import asyncio

from .engines import search_duckduckgo, search_google
from .cache import SimpleCache

app = FastAPI(title="Lucid Search API", description="API de recherche locale avec fallback")

cache = SimpleCache(ttl=300)

# Configuration des moteurs (on les définit comme des coroutines)
engines = [
    {"name": "DuckDuckGo", "func": search_duckduckgo, "cooldown": 30, "max_retries": 2},
    {"name": "Google", "func": search_google, "cooldown": 120, "max_retries": 2},
]

# État des moteurs (simple, on pourrait utiliser une classe)
engine_status = {e["name"]: {"failures": 0, "last_failure": 0, "available": True} for e in engines}

class SearchResult(BaseModel):
    title: str
    snippet: str
    url: str
    source: str

class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    latency: float
    cached: bool
    engine_used: str

def can_use_engine(name: str) -> bool:
    status = engine_status[name]
    if not status["available"]:
        if time.time() - status["last_failure"] > engines[[e["name"] for e in engines].index(name)]["cooldown"]:
            status["available"] = True
            status["failures"] = 0
            return True
        return False
    return True

def mark_failure(name: str):
    status = engine_status[name]
    status["failures"] += 1
    status["last_failure"] = time.time()
    idx = [e["name"] for e in engines].index(name)
    if status["failures"] >= engines[idx]["max_retries"]:
        status["available"] = False

def mark_success(name: str):
    status = engine_status[name]
    status["failures"] = 0
    status["available"] = True

@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., description="Requête de recherche"),
    max_results: int = Query(5, ge=1, le=20)
):
    start = time.time()

    cached = cache.get(q)
    if cached is not None:
        return SearchResponse(
            query=q,
            results=cached,
            latency=time.time() - start,
            cached=True,
            engine_used="cache"
        )

    # Tenter les moteurs dans l'ordre
    for engine_info in engines:
        name = engine_info["name"]
        if not can_use_engine(name):
            continue
        try:
            results_data = await engine_info["func"](q, max_results)
            if results_data:
                mark_success(name)
                results = [SearchResult(**r) for r in results_data]
                cache.set(q, [r.dict() for r in results])
                return SearchResponse(
                    query=q,
                    results=results,
                    latency=time.time() - start,
                    cached=False,
                    engine_used=name
                )
            else:
                # Pas de résultats, on considère comme un échec léger
                mark_failure(name)
        except Exception as e:
            print(f"Erreur avec {name}: {e}")
            mark_failure(name)

    raise HTTPException(status_code=503, detail="Aucun moteur de recherche disponible")

@app.get("/health")
async def health():
    return {"status": "ok", "engines": [e["name"] for e in engines if can_use_engine(e["name"])]}

@app.post("/cache/clear")
async def clear_cache():
    cache.clear()
    return {"message": "Cache vidé"}