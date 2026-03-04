"""
Cortex central - Orchestrateur des agents et de la planification
Version ultra-optimisée pour latence <3s.
"""

import asyncio
import time
import json
import re
import hashlib
from typing import List, Optional, Tuple, Dict, Any
from concurrent.futures import TimeoutError
import threading

from ..providers.manager import ProviderManager
from ..services.prompt_cache import PromptCache
from ..services.web_search import WebSearch
from ..core.executor import TaskExecutor, Task
from ..core.elasticity import ElasticityEngine
from ..utils.logger import logger
from ..utils.metrics import (
    llm_requests_total, llm_request_duration_seconds,
    planning_duration, plan_cache_hits, plan_cache_misses
)
from ..memory import MemoryService
from app.agents.base_agent import BaseAgent
from app.agents.reminder_agent import ReminderAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.document_agent import DocumentAgent
from app.agents.vision.text_extractor import TextExtractorAgent
from app.agents.computer_control_agent import ComputerControlAgent
from app.brain.synapses.event_bus import EventBus


class FrontalCortex:
    """
    Cortex frontal - Orchestrateur des agents et de la planification.
    """

    # Actions simples qui peuvent être routées directement sans LLM
    SIMPLE_ACTIONS = {
        "ouvre": ("ComputerControlAgent", "open_application"),
        "open": ("ComputerControlAgent", "open_application"),
        "lance": ("ComputerControlAgent", "open_application"),
        "tape": ("ComputerControlAgent", "type_text"),
        "type": ("ComputerControlAgent", "type_text"),
        "clique": ("ComputerControlAgent", "click"),
        "click": ("ComputerControlAgent", "click"),
        "capture": ("ComputerControlAgent", "get_screenshot"),
        "screenshot": ("ComputerControlAgent", "get_screenshot"),
    }

    def __init__(self, manager: ProviderManager, bus, event_bus: EventBus,
                 prompt_cache: PromptCache, memory_service: MemoryService,
                 elasticity_engine: ElasticityEngine, config: dict):
        self.manager = manager
        self.bus = bus
        self.event_bus = event_bus
        self.prompt_cache = prompt_cache
        self.memory = memory_service
        self.elasticity = elasticity_engine
        self.config = config
        self.web_search = WebSearch() if config.get("web_search", True) else None

        self.executor = TaskExecutor(max_workers=3, persist_path=None)

        self.agents: Dict[str, BaseAgent] = {}
        self._register_agents()

        self.default_system = "Tu es un assistant IA utile, amical et concis."
        self.plan_timeout = config.get("plan_timeout", 30.0)
        self.max_plan_retries = config.get("max_plan_retries", 1)
        self.enable_memory = config.get("enable_memory", True)
        self.enable_elasticity = config.get("enable_elasticity", True)

        # Mapping des profils vers les noms de modèles réels
        self.model_mapping = {
            "speed": config.get("speed_model", "qwen2.5:3b"),
            "balanced": config.get("balanced_model", "qwen2.5:7b"),
            "quality": config.get("quality_model", "qwen2.5:14b"),
            "nano": "qwen2.5:0.5b"
        }

        self._lock = threading.RLock()
        logger.info(f"🧠 Cortex ultra-optimisé initialisé avec {len(self.agents)} agents")

    def _register_agents(self):
        agents_list = [
            ReminderAgent(self.manager, self.bus, {}),
            KnowledgeAgent(self.manager, self.bus, {
                "max_results": 3,
                "web_search": self.web_search,
                "news_api_key": self.config.get("api_keys", {}).get("news_api_key")
            }),
            DocumentAgent(self.manager, self.bus, {"web_search": self.web_search}),
            TextExtractorAgent(self.manager, self.bus, self.config.get("vision", {})),
            ComputerControlAgent(self.manager, self.bus, {}),
        ]
        for agent in agents_list:
            self.agents[agent.name] = agent

    def _is_simple_query(self, query: str) -> bool:
        """
        Détermine si une requête est simple (réponse directe sans plan).
        Inclut les questions générales sans intention d'action.
        """
        q = query.lower()
        # 1. Routage direct vers une action évidente
        for keyword in self.SIMPLE_ACTIONS:
            if keyword in q:
                # Si c'est une question sur "comment faire", on ne route pas directement
                if "comment" in q and keyword in q:
                    return False
                return True

        # 2. Mots-clés d'action (nécessitent un plan)
        action_keywords = [
            "recherche", "trouve", "document", "rappel", "écran", "crée",
            "fais", "word", "note", "mail", "résumé", "synthèse", "analyse",
            "compare", "liste", "envoie", "programme", "ajoute", "clique",
            "tape", "ouvre", "lance", "souris", "déplace", "organise", "arrange"
        ]
        if any(kw in q for kw in action_keywords):
            return False

        # 3. Questions générales -> simples
        question_words = ["comment", "pourquoi", "est-ce que", "quel", "quelle", "quels", "quelles",
                          "qui", "que", "quoi", "où", "quand", "combien"]
        if any(q.startswith(w) or f" {w} " in q for w in question_words):
            return True

        # 4. Requêtes très courtes (< 10 mots) -> simples
        if len(q.split()) < 10:
            return True

        return False

    def _route_simple_action(self, query: str) -> Optional[Tuple[str, Dict]]:
        """Tente de router une requête simple directement vers un outil sans LLM."""
        q = query.lower()
        for keyword, (agent_name, tool_name) in self.SIMPLE_ACTIONS.items():
            if keyword in q:
                # Extraction basique des paramètres
                if tool_name == "open_application":
                    rest = q.replace(keyword, "").strip()
                    if rest:
                        return agent_name, {"tool": tool_name, "parameters": {"app_name": rest}}
                elif tool_name == "type_text":
                    import re
                    match = re.search(r'"([^"]+)"', query)
                    if match:
                        return agent_name, {"tool": tool_name, "parameters": {"text": match.group(1)}}
                elif tool_name == "click":
                    match = re.search(r'(\d+)[,\s]+(\d+)', query)
                    if match:
                        x, y = int(match.group(1)), int(match.group(2))
                        return agent_name, {"tool": tool_name, "parameters": {"x": x, "y": y}}
                elif tool_name == "get_screenshot":
                    return agent_name, {"tool": tool_name, "parameters": {}}
                # Fallback : l'agent devra interpréter
                return agent_name, {"tool": tool_name, "parameters": {}}
        return None

    def _get_model_for_query(self, query: str, plan_needed: bool = False) -> str:
        """
        Choisit le modèle LLM en fonction de la complexité.
        Pour les réponses directes, on privilégie les modèles rapides.
        """
        if plan_needed:
            if len(query.split()) < 20:
                return self.model_mapping.get("speed", "qwen2.5:3b")
            else:
                return self.model_mapping.get("balanced", "qwen2.5:7b")
        else:
            word_count = len(query.split())
            if word_count < 10:
                # Ultra court -> nano (0.5B)
                return self.model_mapping.get("nano", "qwen2.5:0.5b")
            elif word_count < 30:
                # Court -> speed (3B)
                return self.model_mapping.get("speed", "qwen2.5:3b")
            else:
                # Plus long -> balanced (7B)
                return self.model_mapping.get("balanced", "qwen2.5:7b")

    def _build_agents_description(self) -> str:
        """Version ultra‑courte : juste le nom de l'agent et la liste de ses outils."""
        desc = []
        for name, agent in self.agents.items():
            tool_names = ", ".join([t.name for t in agent.get_tools()])
            desc.append(f"- {name}: {tool_names}")
        return "\n".join(desc)

    def think(self, query: str, system_prompt: Optional[str] = None,
              allow_web_search: bool = True) -> Tuple[str, float]:
        start = time.time()
        logger.info(f"🧠 think() - Requête: {query[:50]}...")
        steps = {}

        # 0. Routage direct pour les actions simples
        t0 = time.time()
        route = self._route_simple_action(query)
        steps['routing'] = time.time() - t0
        if route:
            agent_name, action = route
            logger.info(f"⚡ Routage direct vers {agent_name}.{action['tool']}")
            try:
                agent = self.agents.get(agent_name)
                if agent:
                    result = asyncio.run(agent.execute_tool(action['tool'], action['parameters']))
                    total = time.time() - start
                    logger.info(f"⏱️ Action directe exécutée en {total:.3f}s")
                    return result, total
            except Exception as e:
                logger.error(f"Échec routage direct: {e}")

        # 1. Cache exact (uniquement pour les requêtes simples)
        t0 = time.time()
        cached = None
        if self._is_simple_query(query):
            cached = self.prompt_cache.get(query, system=self.default_system, model="balanced")
        steps['cache_exact'] = time.time() - t0
        if cached:
            logger.info(f"🎯 Réponse trouvée en cache ({steps['cache_exact']:.3f}s)")
            return cached, time.time() - start

        # 2. Enrichissement mémoire (seulement si nécessaire et pas simple)
        t0 = time.time()
        enriched_query = query
        if self.enable_memory and not self._is_simple_query(query):
            working_context = self.memory.get_working_context(n=3)
            if working_context:
                enriched_query = f"Contexte récent:\n{working_context}\n\n{query}"
        steps['enrichissement'] = time.time() - t0

        # 3. Requête simple → réponse directe avec modèle rapide et tokens réduits
        t0 = time.time()
        if self._is_simple_query(query):
            steps['simple_check'] = time.time() - t0
            logger.info("⚡ Requête simple, réponse directe")
            model = self._get_model_for_query(query, plan_needed=False)
            with llm_request_duration_seconds.labels(model=model).time():
                response = self.manager.generate(
                    prompt=enriched_query,
                    system=self.default_system,
                    model=model,
                    temperature=0.5,
                    max_tokens=256  # réduit pour accélérer
                )
            self.prompt_cache.put(query, self.default_system, "balanced", response)
            if self.enable_memory:
                self.memory.add_to_working(query, response)
                self.memory.add_episode(query, response, metadata={"latency": time.time() - start})
            total = time.time() - start
            logger.info(f"⏱️ Timings: {steps} total={total:.3f}s")
            return response, total
        steps['simple_check'] = time.time() - t0

        # 4. Cache de plan (vectoriel) - seuil abaissé à 0.75
        t0 = time.time()
        cached_plan = self._get_cached_plan(enriched_query)
        steps['cache_plan'] = time.time() - t0
        if cached_plan:
            logger.info("📋 Plan trouvé en cache")
            plan_cache_hits.labels(cache_type="vector").inc()
            try:
                final_response = self._execute_plan(cached_plan, enriched_query)
                self.prompt_cache.put(query, self.default_system, "balanced", final_response)
                if self.enable_memory:
                    self.memory.add_to_working(query, final_response)
                    self.memory.add_episode(query, final_response, metadata={"latency": time.time() - start})
                total = time.time() - start
                logger.info(f"⏱️ Timings: {steps} total={total:.3f}s")
                return final_response, total
            except Exception as e:
                logger.error(f"Échec d'exécution du plan caché: {e}")

        plan_cache_misses.labels(cache_type="vector").inc()

        # 5. Génération du plan (modèle adapté)
        t0 = time.time()
        plan = self._generate_plan_with_retry(enriched_query)
        steps['gen_plan'] = time.time() - t0

        # 6. Exécution du plan ou réponse directe
        t0 = time.time()
        if plan and len(plan) > 0:
            self._cache_plan(query, plan)
            try:
                final_response = self._execute_plan(plan, enriched_query, timeout=self.plan_timeout)
                steps['exec_plan'] = time.time() - t0
            except TimeoutError:
                logger.error(f"Timeout exécution plan ({self.plan_timeout}s)")
                final_response = "Désolé, le traitement a pris trop de temps. Veuillez reformuler."
                steps['exec_plan'] = time.time() - t0
            except Exception as e:
                logger.error(f"Erreur exécution plan: {e}")
                final_response = f"Une erreur est survenue: {str(e)}"
                steps['exec_plan'] = time.time() - t0
        else:
            logger.info("⚡ Pas de plan, réponse directe avec modèle rapide")
            model = self._get_model_for_query(query, plan_needed=False)
            with llm_request_duration_seconds.labels(model=model).time():
                response = self.manager.generate(
                    prompt=enriched_query,
                    system=self.default_system,
                    model=model,
                    max_tokens=256
                )
            final_response = response
            steps['direct_response'] = time.time() - t0

        self.prompt_cache.put(query, self.default_system, "balanced", final_response)
        if self.enable_memory:
            self.memory.add_to_working(query, final_response)
            self.memory.add_episode(query, final_response, metadata={"latency": time.time() - start})

        total = time.time() - start
        logger.info(f"⏱️ Timings: {steps} total={total:.3f}s")
        return final_response, total

    def _get_cached_plan(self, query: str) -> Optional[List[Dict]]:
        try:
            return self.prompt_cache.get_plan(query, similarity_threshold=0.75)
        except Exception as e:
            logger.error(f"Erreur récupération plan cache: {e}")
            return None

    def _cache_plan(self, query: str, plan: List[Dict]):
        try:
            self.prompt_cache.put_plan(query, plan)
        except Exception as e:
            logger.error(f"Erreur stockage plan cache: {e}")

    def _generate_plan_with_retry(self, query: str) -> Optional[List[Dict]]:
        for attempt in range(self.max_plan_retries + 1):
            try:
                plan = self._generate_plan(query)
                if plan is not None and self._validate_plan(plan):
                    return plan
                else:
                    logger.warning(f"Plan invalide, tentative {attempt+1}")
            except Exception as e:
                logger.error(f"Exception génération plan: {e}")
            if attempt < self.max_plan_retries:
                time.sleep(0.5 * (attempt + 1))
        return None

    def _generate_plan(self, query: str) -> Optional[List[Dict]]:
        agents_desc = self._build_agents_description()
        prompt = f"""Planifie les actions pour: "{query}"
Agents disponibles:
{agents_desc}

Format JSON attendu : une liste d'étapes. Chaque étape a : id, agent, tool, parameters, description.
Exemples :
- [{{"id":"1","agent":"ComputerControlAgent","tool":"open_application","parameters":{{"app_name":"Notes"}},"description":"Ouvre Notes"}}]
- [{{"id":"1","agent":"ComputerControlAgent","tool":"type_text","parameters":{{"text":"Bonjour","app_name":"Notes"}},"description":"Tape le texte dans Notes"}}]

Réponds uniquement avec le JSON, sinon [].
"""
        try:
            response = self.manager.generate(
                prompt=prompt,
                system="",
                model="speed",
                temperature=0.3,
                max_tokens=512
            )
            cleaned = response.strip()
            try:
                plan = json.loads(cleaned)
                if isinstance(plan, list):
                    return plan
            except json.JSONDecodeError:
                match = re.search(r'(\[.*\])', cleaned, re.DOTALL)
                if match:
                    plan = json.loads(match.group(1))
                    if isinstance(plan, list):
                        return plan
            return None
        except Exception as e:
            logger.error(f"Erreur génération plan: {e}")
            return None

    def _validate_plan(self, plan: List[Dict]) -> bool:
        if not isinstance(plan, list):
            return False
        step_ids = set()
        for step in plan:
            if 'id' not in step or 'agent' not in step:
                return False
            step_ids.add(step['id'])
            if step['agent'] not in self.agents:
                return False
        return True

    def _execute_plan(self, plan: List[Dict], query: str, timeout: float = 30.0) -> str:
        if not plan:
            return "Aucune action."

        step_results = {}
        task_futures = {}
        step_tasks = {}

        for step in plan:
            task = Task(
                id=step.get("id", str(time.time())),
                name=step.get("description", step["agent"]),
                func=self._execute_step,
                args=(step, step_results),
                kwargs={}
            )
            if "depends_on" in step:
                task.dependencies = step["depends_on"]
            task_id = self.executor.submit(task)
            task_futures[task_id] = step
            step_tasks[step['id']] = task_id

        from concurrent.futures import wait, FIRST_EXCEPTION, TimeoutError as FuturesTimeout
        futures = [self.executor.get_future(task_id) for task_id in task_futures.keys()]

        try:
            done, not_done = wait(futures, timeout=timeout, return_when=FIRST_EXCEPTION)
            if not_done:
                for f in not_done:
                    f.cancel()
                raise TimeoutError(f"Plan non terminé après {timeout}s")
            for f in done:
                if f.exception():
                    raise f.exception()
            results = []
            for step in plan:
                task_id = step_tasks[step['id']]
                try:
                    result = self.executor.get_task_result(task_id, timeout=0)
                    results.append(result)
                except Exception as e:
                    return f"Échec de l'étape '{step.get('description')}': {e}"
        except TimeoutError as e:
            for tid in task_futures:
                self.executor.cancel_task(tid)
            raise
        except Exception as e:
            for tid in task_futures:
                self.executor.cancel_task(tid)
            raise

        if len(results) == 1:
            return results[0]
        else:
            return self._synthesize(query, results)

    def _execute_step(self, *args):
        if len(args) < 2:
            raise Exception(f"Arguments insuffisants: {len(args)}")
        step = args[-2]
        step_results = args[-1]

        agent_name = step.get("agent")
        tool_name = step.get("tool")
        params = step.get("parameters", {})

        if isinstance(params, str):
            try:
                params = json.loads(params)
            except:
                params = {"content": params}
        if not isinstance(params, dict):
            params = {}

        agent = self.agents.get(agent_name)
        if not agent:
            raise Exception(f"Agent {agent_name} inconnu")

        try:
            if tool_name:
                result = asyncio.run(agent.execute_tool(tool_name, params))
            else:
                result = asyncio.run(agent.handle(params.get("query", "")))
            logger.info(f"✅ Étape exécutée avec succès: {step.get('description', '')}")
            return result
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'exécution de l'étape {step.get('description', '')}: {e}")
            raise

    def _synthesize(self, query: str, results: List[str]) -> str:
        if len(results) == 0:
            return "Aucun résultat."
        if len(results) == 1:
            return results[0]

        total_len = sum(len(r) for r in results)
        if total_len < 500 and len(results) <= 3:
            return "\n\n".join(results)

        prompt = f"Résultats pour \"{query}\":\n" + "\n---\n".join(results) + "\nSynthèse concise:"
        try:
            return self.manager.generate(prompt, self.default_system, model="speed", max_tokens=256)
        except Exception as e:
            logger.error(f"Erreur synthèse: {e}")
            return "\n\n".join(results)

    def stop(self):
        self.executor.shutdown()
        logger.info("Cortex arrêté.")