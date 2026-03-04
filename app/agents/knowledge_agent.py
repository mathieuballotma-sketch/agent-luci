"""
Agent spécialisé dans la recherche d'informations.
Utilise la validation Pydantic pour les paramètres des outils.
"""

import json
import re
import httpx
from typing import Optional
from pydantic import BaseModel, Field
from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


class KnowledgeAgentWebSearchContract(BaseModel):
    query: str = Field(..., description="La requête de recherche")
    max_results: int = Field(3, description="Nombre maximum de résultats", ge=1, le=10)

class KnowledgeAgentWikipediaSummaryContract(BaseModel):
    query: str = Field(..., description="Le titre ou sujet de l'article")

class KnowledgeAgentWikipediaSearchContract(BaseModel):
    query: str = Field(..., description="La requête de recherche")

class KnowledgeAgentArxivSearchContract(BaseModel):
    query: str = Field(..., description="La requête de recherche")

class KnowledgeAgentNewsHeadlinesContract(BaseModel):
    query: str = Field(..., description="Sujet des actualités")


class KnowledgeAgent(BaseAgent):
    """
    Agent de connaissances : recherche web, Wikipedia, arXiv, actualités.
    """

    def __init__(self, llm_service, bus, config):
        super().__init__("KnowledgeAgent", llm_service, bus)
        self.user_agent = "LucidAgent/1.0 (contact@example.com)"
        self.news_api_key = config.get("news_api_key")
        self.max_results = config.get("max_results", 3)
        self.web_search = config.get("web_search")  # ancien service (fallback)
        self.search_api_url = "http://127.0.0.1:8000/search"
        self.timeout = config.get("timeout", 10)

    def get_tools(self) -> list:
        return [
            Tool(
                name="web_search",
                description="Recherche sur le web (via API locale ou DuckDuckGo)",
                contract=KnowledgeAgentWebSearchContract,
            ),
            Tool(
                name="wikipedia_summary",
                description="Résumé d'un article Wikipedia",
                contract=KnowledgeAgentWikipediaSummaryContract,
            ),
            Tool(
                name="wikipedia_search",
                description="Recherche d'articles Wikipedia",
                contract=KnowledgeAgentWikipediaSearchContract,
            ),
            Tool(
                name="arxiv_search",
                description="Recherche d'articles scientifiques sur arXiv",
                contract=KnowledgeAgentArxivSearchContract,
            ),
            Tool(
                name="news_headlines",
                description="Recherche d'actualités (nécessite une clé API NewsAPI)",
                contract=KnowledgeAgentNewsHeadlinesContract,
            ),
        ]

    # Implémentations des outils
    async def _tool_web_search(self, query: str, max_results: int = 3) -> str:
        # Essayer l'API locale
        api_result = await self._call_search_api(query, max_results)
        if api_result is not None:
            return api_result
        # Fallback DuckDuckGo
        if self.web_search:
            logger.info("Fallback sur DuckDuckGo direct")
            try:
                # Supposons que web_search.search est synchrone, on le met dans un executor
                import asyncio
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(None, self.web_search.search, query, max_results)
                if not results:
                    return f"Aucun résultat web trouvé pour '{query}'."
                output = f"Résultats web pour '{query}':\n"
                for r in results:
                    title = r.get('title', '')
                    body = r.get('body', '')[:200]
                    url = r.get('url', '')
                    output += f"- {title}\n  {body}...\n  ({url})\n\n"
                return output
            except Exception as e:
                logger.error(f"Erreur fallback web_search: {e}")
                return f"Erreur lors de la recherche web: {e}"
        else:
            return "Recherche web non disponible."

    async def _tool_wikipedia_summary(self, query: str) -> str:
        return await self._wikipedia_summary(query)

    async def _tool_wikipedia_search(self, query: str) -> str:
        return await self._wikipedia_search(query)

    async def _tool_arxiv_search(self, query: str) -> str:
        return await self._arxiv_search(query)

    async def _tool_news_headlines(self, query: str) -> str:
        if not self.news_api_key:
            return "Clé API News non configurée."
        return await self._news_headlines(query)

    # Méthodes privées asynchrones
    async def _call_search_api(self, query: str, max_results: int = 3) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    self.search_api_url,
                    params={"q": query, "max_results": max_results}
                )
                if resp.status_code != 200:
                    logger.error(f"API recherche erreur {resp.status_code}")
                    return None
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    return f"Aucun résultat trouvé pour '{query}'."
                output = f"Résultats web pour '{query}':\n"
                for r in results:
                    title = r.get('title', '')
                    snippet = r.get('snippet', '')[:200]
                    url = r.get('url', '')
                    source = r.get('source', '')
                    output += f"- [{source}] {title}\n  {snippet}...\n  ({url})\n\n"
                return output
        except Exception as e:
            logger.error(f"Erreur appel API recherche: {e}")
            return None

    async def _wikipedia_summary(self, query: str) -> str:
        import requests
        try:
            loop = asyncio.get_event_loop()
            # Essayer français
            url = "https://fr.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(query)
            resp = await loop.run_in_executor(None, lambda: requests.get(url, headers={"User-Agent": self.user_agent}, timeout=self.timeout))
            if resp.status_code == 200:
                data = resp.json()
                return f"Wikipédia (fr) : {data.get('extract', 'Pas de résumé disponible.')}"
            # Sinon anglais
            url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(query)
            resp = await loop.run_in_executor(None, lambda: requests.get(url, headers={"User-Agent": self.user_agent}, timeout=self.timeout))
            if resp.status_code == 200:
                data = resp.json()
                return f"Wikipedia (en) : {data.get('extract', 'No summary available.')}"
            return f"Impossible de trouver une page Wikipedia pour '{query}'."
        except Exception as e:
            logger.error(f"Erreur Wikipedia: {e}")
            return f"Erreur lors de l'appel à Wikipedia : {str(e)}"

    async def _wikipedia_search(self, query: str) -> str:
        import requests
        try:
            loop = asyncio.get_event_loop()
            url = "https://fr.wikipedia.org/w/api.php"
            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": self.max_results
            }
            resp = await loop.run_in_executor(None, lambda: requests.get(url, params=params, headers={"User-Agent": self.user_agent}, timeout=self.timeout))
            data = resp.json()
            results = data.get("query", {}).get("search", [])
            if not results:
                return f"Aucun article trouvé pour '{query}'."
            output = f"Articles Wikipedia correspondant à '{query}':\n"
            for r in results:
                output += f"- {r['title']}\n"
            return output
        except Exception as e:
            logger.error(f"Erreur recherche Wikipedia: {e}")
            return f"Erreur lors de la recherche Wikipedia : {str(e)}"

    async def _arxiv_search(self, query: str) -> str:
        import requests
        import xml.etree.ElementTree as ET
        try:
            loop = asyncio.get_event_loop()
            url = "http://export.arxiv.org/api/query"
            params = {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": self.max_results
            }
            resp = await loop.run_in_executor(None, lambda: requests.get(url, params=params, timeout=self.timeout))
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", ns)
            if not entries:
                return f"Aucun article arXiv trouvé pour '{query}'."
            output = f"Articles arXiv pour '{query}':\n"
            for entry in entries:
                title = entry.find("atom:title", ns).text
                summary = entry.find("atom:summary", ns).text
                output += f"- {title}\n  {summary[:200]}...\n\n"
            return output
        except Exception as e:
            logger.error(f"Erreur arXiv: {e}")
            return f"Erreur lors de la recherche arXiv : {str(e)}"

    async def _news_headlines(self, query: str) -> str:
        if not self.news_api_key:
            return "Clé API News non configurée."
        import requests
        try:
            loop = asyncio.get_event_loop()
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "apiKey": self.news_api_key,
                "pageSize": self.max_results,
                "language": "fr"
            }
            resp = await loop.run_in_executor(None, lambda: requests.get(url, params=params, timeout=self.timeout))
            data = resp.json()
            if data.get("status") != "ok":
                return f"Erreur NewsAPI : {data.get('message', 'inconnue')}"
            articles = data.get("articles", [])
            if not articles:
                return f"Aucune actualité trouvée pour '{query}'."
            output = f"Actualités sur '{query}':\n"
            for a in articles:
                title = a.get("title", "Sans titre")
                desc = a.get("description", "")
                output += f"- {title}\n  {desc}\n\n"
            return output
        except Exception as e:
            logger.error(f"Erreur NewsAPI: {e}")
            return f"Erreur lors de la récupération des actualités : {str(e)}"

    # Logique de décision
    def can_handle(self, query: str) -> bool:
        q = query.lower()
        doc_keywords = ["document word", "crée un document", "fais un document",
                        "résumé word", "fais un résumé", "word document"]
        if any(kw in q for kw in doc_keywords):
            return False
        keywords = [
            "recherche", "wikipédia", "actualité", "définition",
            "information sur", "qu'est-ce que", "c'est quoi",
            "news", "arxiv", "article", "savoir", "trouve",
            "donne moi des infos", "explique"
        ]
        return any(kw in q for kw in keywords)

    async def handle(self, query: str) -> str:
        q_lower = query.lower()
        # Cas spécial actualités sans clé API
        if ("actualité" in q_lower or "actualités" in q_lower or "news" in q_lower) and not self.news_api_key:
            if self.web_search:
                logger.info("🔍 Utilisation de la recherche web pour les actualités")
                results = await self._run_web_search(query, self.max_results)
                if results:
                    summary = await self._summarize_results(query, results)
                    return f"📰 Résumé de l'actualité :\n{summary}"
                else:
                    return "Aucune actualité trouvée."
            else:
                return "La recherche web n'est pas disponible pour les actualités."

        # Construction du prompt pour choisir l'outil
        tools_desc = "\n".join([f"- {t.name}: {t.description}" for t in self.get_tools()])
        prompt = f"""
Tu es un assistant spécialisé dans la recherche d'informations. Voici la demande : "{query}"

Outils disponibles :
{tools_desc}

Choisis l'outil le plus adapté et fournis les paramètres nécessaires.
Réponds UNIQUEMENT avec un JSON de la forme :
{{"tool": "nom_outil", "parameters": {{"param1": "valeur1", ...}}}}
Si aucun outil n'est pertinent, réponds {{"tool": "none"}}.
"""
        try:
            response = self.ask_llm(prompt, temperature=0.3)
            data = self.extract_json_from_response(response)
            if data and isinstance(data, dict):
                tool = data.get("tool")
                params = data.get("parameters", {})
                if tool and tool != "none":
                    return await self.execute_tool(tool, params)
            # Fallback : recherche Wikipedia par défaut
            return await self._tool_wikipedia_summary(query=query)
        except Exception as e:
            logger.error(f"Erreur dans KnowledgeAgent.handle: {e}")
            return f"Erreur lors de la recherche : {str(e)}"

    async def _run_web_search(self, query: str, max_results: int) -> list:
        if not self.web_search:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.web_search.search, query, max_results)

    async def _summarize_results(self, query: str, results: list) -> str:
        content = "\n".join([f"- {r['title']}: {r['body'][:200]}" for r in results])
        prompt = f"""
Voici des résultats de recherche pour la requête "{query}" :
{content}
Fais un résumé concis et informatif de ces informations.
"""
        return self.ask_llm(prompt)