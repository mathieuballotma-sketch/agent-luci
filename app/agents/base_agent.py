"""
BaseAgent - Classe de base pour tous les agents.
v3 : ajout de ask_llm_async, implémentation par défaut de handle et publication d'erreurs.
"""

import asyncio
import inspect
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from ..utils.logger import logger
from ..utils.metrics import tool_execution_duration, tool_execution_errors


class Tool:
    def __init__(self, name: str, description: str, contract: Type[BaseModel]):
        self.name = name
        self.description = description
        self.contract = contract

    def validate(self, params: Dict[str, Any]) -> BaseModel:
        try:
            return self.contract(**params)
        except ValidationError as e:
            logger.error(f"Erreur de validation [{self.name}]: {e}")
            raise


class BaseAgent(ABC):
    def __init__(self, name: str, llm_service, bus):
        self.name = name
        self.llm = llm_service
        self.bus = bus
        self._tools_cache: Optional[Dict[str, Tool]] = None
        # Référence à l'event bus (sera injectée par le cortex)
        self.event_bus = None
        logger.info(f"🤖 Agent '{self.name}' initialisé")

    @abstractmethod
    def can_handle(self, query: str) -> bool:
        pass

    async def handle(self, query: str) -> str:
        """
        Comportement par défaut : interroger le LLM.
        Les sous-classes peuvent surcharger cette méthode.
        """
        return await self.ask_llm_async(query)

    def get_tools(self) -> List[Tool]:
        return []

    def _get_tool_by_name(self, name: str) -> Optional[Tool]:
        if self._tools_cache is None:
            self._tools_cache = {t.name: t for t in self.get_tools()}
        return self._tools_cache.get(name)

    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> str:
        start = time.time()
        tool = self._get_tool_by_name(tool_name)
        if not tool:
            msg = f"Outil '{tool_name}' non trouvé dans {self.name}"
            logger.error(msg)
            tool_execution_errors.labels(agent=self.name, tool=tool_name).inc()
            return f"Erreur: {msg}"

        try:
            validated = tool.validate(parameters)
            logger.debug(f"Paramètres validés [{tool_name}]: {validated.dict()}")
        except ValidationError as e:
            msg = f"Paramètres invalides [{tool_name}]: {e}"
            logger.error(msg)
            tool_execution_errors.labels(agent=self.name, tool=tool_name).inc()
            return f"Erreur de validation: {msg}"

        method_name = f"_tool_{tool_name}"
        if not hasattr(self, method_name):
            msg = f"Méthode '{method_name}' non implémentée dans {self.name}"
            logger.error(msg)
            tool_execution_errors.labels(agent=self.name, tool=tool_name).inc()
            return f"Erreur: {msg}"

        method = getattr(self, method_name)
        params = validated.dict(exclude_none=True)

        try:
            if inspect.iscoroutinefunction(method):
                result = await method(**params)
            else:
                result = method(**params)
            duration = time.time() - start
            tool_execution_duration.labels(agent=self.name, tool=tool_name).observe(duration)
            logger.info(f"✅ [{tool_name}] exécuté en {duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start
            logger.error(f"Erreur exécution [{tool_name}]: {e}")
            tool_execution_errors.labels(agent=self.name, tool=tool_name).inc()
            # Publier l'erreur sur le bus d'événements
            asyncio.create_task(self._publish_error(tool_name, str(e)))
            return f"Erreur lors de l'exécution: {str(e)}"

    async def _publish_error(self, tool: str, error: str):
        """Publie une erreur d'outil sur le bus d'événements."""
        if self.event_bus:
            await self.event_bus.publish(
                "tool.error",
                {"agent": self.name, "tool": tool, "error": error},
                self.name
            )

    def ask_llm(self, prompt: str, system_prompt: Optional[str] = None,
                model: str = "balanced", temperature: float = 0.5,
                max_tokens: int = 512) -> str:
        try:
            response = self.llm.generate(
                prompt=prompt,
                system=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response if response else "[RÉPONSE VIDE]"
        except Exception as e:
            logger.error(f"Erreur LLM [{self.name}]: {e}")
            return f"Erreur LLM: {str(e)}"

    async def ask_llm_async(self, prompt: str, system_prompt: Optional[str] = None,
                            model: str = "balanced", temperature: float = 0.5,
                            max_tokens: int = 512) -> str:
        """Version asynchrone de ask_llm (exécute dans un thread)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.ask_llm, prompt, system_prompt, model, temperature, max_tokens
        )

    def extract_json_from_response(self, response: str) -> Optional[Dict]:
        cleaned = re.sub(r'^```json\s*', '', response.strip())
        cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            for pattern in [r'(\{.*\})', r'(\[.*\])']:
                match = re.search(pattern, cleaned, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        continue
        logger.warning(f"JSON non extractible: {cleaned[:200]}…")
        return None