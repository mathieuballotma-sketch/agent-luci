"""
Cortex central - Orchestrateur des agents et de la planification
Version avec prédiction asynchrone (NanoPredictor) pour anticiper les actions.
"""

import asyncio
import time
import json
import re
import hashlib
import threading
from typing import List, Optional, Tuple, Dict, Any, Callable
from concurrent.futures import TimeoutError
from collections import defaultdict

from ..providers.manager import ProviderManager
from ..services.prompt_cache import PromptCache
from ..services.web_search import WebSearch
from ..core.executor import TaskExecutor, Task
from ..core.elasticity import ElasticityEngine
from ..utils.logger import logger
from ..utils.metrics import (
    llm_requests_total, llm_request_duration_seconds,
    planning_duration, plan_cache_hits, plan_cache_misses,
    record_cortex_step
)
from ..memory import MemoryService
from app.agents.base_agent import BaseAgent
from app.agents.reminder_agent import ReminderAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.document_agent import DocumentAgent
from app.agents.vision.text_extractor import TextExtractorAgent
from app.agents.computer_control_agent import ComputerControlAgent
from app.brain.synapses.event_bus import EventBus


class NanoPredictor:
    """
    Prédicteur asynchrone qui analyse le texte tapé en temps réel et prépare des actions potentielles.
    Utilise le modèle nano (0.5B) pour inférer l'intention.
    """

    def __init__(self, manager: ProviderManager, agents: Dict[str, BaseAgent]):
        self.manager = manager
        self.agents = agents
        self.current_text = ""
        self.last_prediction = None      # (action_plan, timestamp)
        self.last_update = 0
        self._lock = threading.RLock()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("🧠 NanoPredictor démarré")

    def update_partial_input(self, text: str):
        """Appelé par le HUD à chaque modification du texte."""
        with self._lock:
            self.current_text = text

    def get_prediction(self) -> Optional[Dict]:
        """Retourne la dernière prédiction si elle est encore valide (moins de 5 secondes)."""
        with self._lock:
            if self.last_prediction and time.time() - self.last_prediction[1] < 5.0:
                return self.last_prediction[0]
        return None

    def _run(self):
        """Boucle de prédiction : toutes les 1s, si le texte a changé, lance une inférence."""
        last_text = ""
        while self._running:
            time.sleep(1.0)
            with self._lock:
                text = self.current_text
            if text and text != last_text and len(text) > 3:
                last_text = text
                self._predict(text)

    def _predict(self, text: str):
        """Appelle le LLM nano pour interpréter le texte partiel et générer une action candidate."""
        # Construction du prompt (similaire au semantic parsing)
        tools_desc = []
        for agent_name, agent in self.agents.items():
            for tool in agent.get_tools():
                # On ne donne que le nom et une description courte pour éviter de surcharger
                tools_desc.append(f"- {agent_name}.{tool.name}: {tool.description[:100]}")
        tools_str = "\n".join(tools_desc)

        prompt = f"""
Tu es un assistant qui prédit l'action que l'utilisateur est en train de décrire.
Voici les outils disponibles :
{tools_str}

Le début de la demande : "{text}"

Si tu penses pouvoir compléter cette demande en une ou plusieurs actions, retourne une liste JSON d'actions.
Chaque action a : "agent", "tool", "parameters" (dict), "description" (optionnelle).
Si tu n'as pas assez d'informations, retourne [].
Exemple : [{{"agent": "ComputerControlAgent", "tool": "open_application", "parameters": {{"app_name": "Notes"}}, "description": "Ouvre Notes"}}]
Réponds uniquement avec le JSON.
"""
        try:
            response = self.manager.generate(
                prompt=prompt,
                system="",
                model="nano",
                temperature=0.1,
                max_tokens=256,
                timeout=3.0
            )
            cleaned = response.strip()
            try:
                plan = json.loads(cleaned)
            except json.JSONDecodeError:
                match = re.search(r'(\[.*\])', cleaned, re.DOTALL)
                if match:
                    plan = json.loads(match.group(1))
                else:
                    plan = []
            with self._lock:
                self.last_prediction = (plan, time.time())
            logger.debug(f"NanoPredictor: prédiction pour '{text[:30]}...' → {plan}")
        except Exception as e:
            logger.error(f"Erreur dans NanoPredictor: {e}")

    def stop(self):
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=1)


class ActionSelector:
    """
    Sélecteur de chemin basé sur le principe de moindre action.
    Maintient pour chaque type de requête une liste de chemins ordonnés
    par temps de réponse moyen (du plus rapide au plus lent).
    En cas d'échec d'un chemin, le suivant est essayé.
    """

    def __init__(self):
        self.stats = defaultdict(lambda: defaultdict(lambda: {"sum": 0.0, "count": 0, "failures": 0}))
        self.paths = {}

    def register_path(self, path_id: str, func: Callable, description: str = ""):
        self.paths[path_id] = {"func": func, "description": description}

    def get_paths_for_query(self, query: str) -> List[Tuple[str, Callable]]:
        query_type = self._classify_query(query)
        type_stats = self.stats[query_type]

        averages = {}
        for path_id in self.paths:
            s = type_stats.get(path_id, {"sum": 0.0, "count": 0})
            averages[path_id] = s["sum"] / s["count"] if s["count"] > 0 else float('inf')

        sorted_paths = sorted(self.paths.keys(), key=lambda pid: averages[pid])
        return [(pid, self.paths[pid]["func"]) for pid in sorted_paths]

    def record_success(self, query: str, path_id: str, duration: float):
        query_type = self._classify_query(query)
        s = self.stats[query_type][path_id]
        s["sum"] += duration
        s["count"] += 1

    def record_failure(self, query: str, path_id: str):
        query_type = self._classify_query(query)
        s = self.stats[query_type][path_id]
        s["failures"] += 1
        s["sum"] += 10.0
        s["count"] += 1

    def _classify_query(self, query: str) -> str:
        q = query.lower().strip()
        greetings = ["bonjour", "salut", "hello", "coucou", "merci", "au revoir", "bye", "hi"]
        if q in greetings or any(g in q for g in greetings):
            return "greeting"
        action_keywords = ["ouvre", "lance", "tape", "clique", "capture", "open", "launch", "type", "click", "écris", "ecris"]
        if any(kw in q for kw in action_keywords):
            if " et " in q or " puis " in q:
                return "multi_action"
            return "action"
        return "simple" if len(q.split()) < 5 else "complex"


class FrontalCortex:
    """
    Cortex frontal - Orchestrateur des agents et de la planification.
    """

    SIMPLE_ACTIONS = {
        "ouvre": ("ComputerControlAgent", "open_application"),
        "open": ("ComputerControlAgent", "open_application"),
        "lance": ("ComputerControlAgent", "open_application"),
        "tape": ("ComputerControlAgent", "type_text"),
        "écris": ("ComputerControlAgent", "type_text"),
        "ecris": ("ComputerControlAgent", "type_text"),
        "type": ("ComputerControlAgent", "type_text"),
        "clique": ("ComputerControlAgent", "click"),
        "click": ("ComputerControlAgent", "click"),
        "capture": ("ComputerControlAgent", "get_screenshot"),
        "screenshot": ("ComputerControlAgent", "get_screenshot"),
    }

    APP_ALIASES = {
        "note": "Notes",
        "notes": "Notes",
        "calculatrice": "Calculator",
        "calculette": "Calculator",
        "safari": "Safari",
        "mail": "Mail",
        "calendrier": "Calendar",
        "rappels": "Reminders",
        "reminders": "Reminders",
        "calendar": "Calendar",
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
        self.base_plan_timeout = config.get("plan_timeout", 30.0)
        self.max_plan_retries = config.get("max_plan_retries", 1)
        self.enable_memory = config.get("enable_memory", True)
        self.enable_elasticity = config.get("enable_elasticity", True)

        self.model_mapping = {
            "speed": config.get("speed_model", "qwen2.5:3b"),
            "balanced": config.get("balanced_model", "qwen2.5:7b"),
            "quality": config.get("quality_model", "qwen2.5:14b"),
            "nano": "qwen2.5:0.5b"
        }

        # Prédicteur asynchrone
        self.predictor = NanoPredictor(manager, self.agents)

        self.action_selector = ActionSelector()
        self._register_paths()

        self._lock = threading.RLock()
        logger.info(f"🧠 Cortex avec prédicteur initialisé avec {len(self.agents)} agents")

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

    def _register_paths(self):
        self.action_selector.register_path(
            "prediction_cache",
            self._execute_prediction_cache,
            "Action anticipée par le prédicteur"
        )
        self.action_selector.register_path(
            "direct_action",
            self._execute_direct_action,
            "Exécution directe d'une action simple (mots-clés)"
        )
        self.action_selector.register_path(
            "multi_action",
            self._execute_multi_action,
            "Exécution séquentielle de plusieurs actions"
        )
        self.action_selector.register_path(
            "semantic_parsing",
            self._execute_semantic_parsing,
            "Interprétation sémantique via LLM nano"
        )
        self.action_selector.register_path(
            "cache_response",
            self._get_cached_response,
            "Réponse depuis le cache exact"
        )
        self.action_selector.register_path(
            "llm_nano",
            lambda q: self._call_llm(q, "nano"),
            "LLM nano (0.5B) - réponse directe"
        )
        self.action_selector.register_path(
            "llm_speed",
            lambda q: self._call_llm(q, "speed"),
            "LLM speed (3B) - réponse directe"
        )
        self.action_selector.register_path(
            "llm_balanced",
            lambda q: self._call_llm(q, "balanced"),
            "LLM balanced (7B) - réponse directe"
        )
        self.action_selector.register_path(
            "plan_generation",
            self._generate_and_execute_plan,
            "Génération et exécution d'un plan"
        )

    def _execute_prediction_cache(self, query: str) -> str:
        """Utilise la prédiction anticipée si elle correspond à la requête finale."""
        pred = self.predictor.get_prediction()
        if not pred:
            raise Exception("Aucune prédiction disponible")
        # On pourrait vérifier que la requête finale correspond au début de la prédiction,
        # mais ici on fait confiance au prédicteur.
        results = []
        for act in pred:
            agent_name = act.get("agent")
            tool_name = act.get("tool")
            params = act.get("parameters", {})
            agent = self.agents.get(agent_name)
            if not agent:
                raise Exception(f"Agent {agent_name} inconnu")
            result = asyncio.run(agent.execute_tool(tool_name, params))
            if result.startswith("❌"):
                raise Exception(f"Échec de l'action {tool_name}: {result}")
            results.append(result)
        return "\n".join(results)

    def _execute_direct_action(self, query: str) -> str:
        route = self._route_simple_action(query)
        if route:
            agent_name, action = route
            agent = self.agents.get(agent_name)
            if agent:
                result = asyncio.run(agent.execute_tool(action['tool'], action['parameters']))
                if result.startswith("❌"):
                    raise Exception(f"L'outil a retourné une erreur: {result}")
                return result
        raise Exception("Aucune action directe trouvée")

    def _execute_multi_action(self, query: str) -> str:
        parts = re.split(r"\s+(et|puis)\s+", query, flags=re.IGNORECASE)
        results = []
        for part in parts:
            part = part.strip()
            if not part or part.lower() in ["et", "puis"]:
                continue
            route = self._route_simple_action(part)
            if not route:
                raise Exception(f"Impossible de traiter la sous-action: {part}")
            agent_name, action = route
            agent = self.agents.get(agent_name)
            if not agent:
                raise Exception(f"Agent {agent_name} introuvable")
            result = asyncio.run(agent.execute_tool(action['tool'], action['parameters']))
            if result.startswith("❌"):
                raise Exception(f"Échec de la sous-action: {result}")
            results.append(result)
        if results:
            return "\n".join(results)
        raise Exception("Aucune action multiple trouvée")

    def _execute_semantic_parsing(self, query: str) -> str:
        """Interprète la requête avec le LLM nano et exécute les actions."""
        # Construction du prompt
        tools_desc = []
        for agent_name, agent in self.agents.items():
            for tool in agent.get_tools():
                tools_desc.append(f"- {agent_name}.{tool.name}: {tool.description}")
        tools_str = "\n".join(tools_desc)

        prompt = f"""
Tu es un assistant qui traduit des demandes utilisateur en actions exécutables.
Voici les outils disponibles :
{tools_str}

La demande : "{query}"

Génère une liste d'actions au format JSON. Chaque action a :
- "agent": nom de l'agent
- "tool": nom de l'outil
- "parameters": dictionnaire des paramètres
- "description": courte description (optionnelle)

Exemple pour "ouvre notes et écris bonjour" :
[
  {{"agent": "ComputerControlAgent", "tool": "open_application", "parameters": {{"app_name": "Notes"}}, "description": "Ouvre Notes"}},
  {{"agent": "ComputerControlAgent", "tool": "type_text", "parameters": {{"text": "bonjour"}}, "description": "Écrit bonjour"}}
]

Si la demande ne correspond à aucune action, retourne [].
Réponds uniquement avec le JSON.
"""
        try:
            response = self.manager.generate(
                prompt=prompt,
                system="",
                model="nano",
                temperature=0.1,
                max_tokens=512,
                timeout=5.0
            )
            cleaned = response.strip()
            try:
                actions = json.loads(cleaned)
            except json.JSONDecodeError:
                match = re.search(r'(\[.*\])', cleaned, re.DOTALL)
                if match:
                    actions = json.loads(match.group(1))
                else:
                    raise Exception("Impossible de parser la réponse du LLM")

            if not isinstance(actions, list):
                raise Exception("La réponse n'est pas une liste")

            if not actions:
                raise Exception("Aucune action générée")

            results = []
            for act in actions:
                agent_name = act.get("agent")
                tool_name = act.get("tool")
                params = act.get("parameters", {})
                agent = self.agents.get(agent_name)
                if not agent:
                    raise Exception(f"Agent {agent_name} inconnu")
                result = asyncio.run(agent.execute_tool(tool_name, params))
                if result.startswith("❌"):
                    raise Exception(f"Échec de l'action {tool_name}: {result}")
                results.append(result)
            return "\n".join(results)

        except Exception as e:
            raise Exception(f"Échec de l'interprétation sémantique: {e}")

    def _get_cached_response(self, query: str) -> str:
        cached = self.prompt_cache.get(query, system=self.default_system, model="balanced")
        if cached:
            return cached
        raise Exception("Cache miss")

    def _call_llm(self, query: str, model_profile: str) -> str:
        model_name = self.model_mapping.get(model_profile)
        if not model_name:
            raise Exception(f"Profil de modèle inconnu: {model_profile}")
        enriched_query = self._enrich_query(query)
        word_count = len(query.split())
        timeout = min(5.0 * (1 + word_count / 50), 30.0)
        response = self.manager.generate(
            prompt=enriched_query,
            system=self.default_system,
            model=model_name,
            temperature=0.5,
            max_tokens=256,
            timeout=timeout
        )
        self.prompt_cache.put(query, self.default_system, "balanced", response)
        if self.enable_memory:
            self.memory.add_to_working(query, response)
            self.memory.add_episode(query, response, metadata={"latency": time.time()})
        return response

    def _generate_and_execute_plan(self, query: str) -> str:
        plan = self._generate_plan_with_retry(query)
        if not plan:
            raise Exception("Plan invalide")
        self._cache_plan(query, plan)
        timeout = self._get_dynamic_timeout(query, plan_needed=True)
        final_response = self._execute_plan(plan, query, timeout=timeout)
        self.prompt_cache.put(query, self.default_system, "balanced", final_response)
        if self.enable_memory:
            self.memory.add_to_working(query, final_response)
            self.memory.add_episode(query, final_response, metadata={"latency": time.time()})
        return final_response

    def _safe_fallback(self, query: str) -> str:
        logger.warning("Utilisation du fallback sécurisé")
        return "Désolé, je n'ai pas pu traiter votre demande. Veuillez réessayer."

    # -----------------------------------------------------------------------
    # Méthodes de support
    # -----------------------------------------------------------------------

    def _route_simple_action(self, query: str) -> Optional[Tuple[str, Dict]]:
        q = query.lower()
        for keyword, (agent_name, tool_name) in self.SIMPLE_ACTIONS.items():
            if keyword in q:
                if tool_name == "open_application":
                    rest = q.replace(keyword, "").strip()
                    if rest.startswith(("et", "puis")):
                        continue
                    rest = re.sub(r'^["\'](.*)["\']$', r'\1', rest)
                    logger.debug(f"[route] rest avant normalisation: {rest}")
                    normalized = self.APP_ALIASES.get(rest.lower())
                    if normalized:
                        rest = normalized
                        logger.debug(f"[route] normalisé en: {rest}")
                    return agent_name, {"tool": tool_name, "parameters": {"app_name": rest}}
                elif tool_name == "type_text":
                    pattern = r'\b' + re.escape(keyword) + r'\s*"([^"]+)"'
                    match = re.search(pattern, query, re.IGNORECASE)
                    if match:
                        text = match.group(1)
                        app_match = re.search(r'(?:dans|sur)\s+([a-zA-Z]+)', q, re.IGNORECASE)
                        app_name = app_match.group(1) if app_match else None
                        params = {"text": text}
                        if app_name:
                            params["app_name"] = app_name
                        return agent_name, {"tool": tool_name, "parameters": params}
                elif tool_name == "click":
                    match = re.search(r'(\d+)[,\s]+(\d+)', query)
                    if match:
                        x, y = int(match.group(1)), int(match.group(2))
                        return agent_name, {"tool": tool_name, "parameters": {"x": x, "y": y}}
                elif tool_name == "get_screenshot":
                    return agent_name, {"tool": tool_name, "parameters": {}}
        return None

    def _get_dynamic_timeout(self, query: str, plan_needed: bool) -> float:
        base = self.base_plan_timeout if plan_needed else 5.0
        word_count = len(query.split())
        estimated = base * (1 + word_count / 100)
        return min(estimated, self.base_plan_timeout * 2)

    def _enrich_query(self, query: str) -> str:
        if self.enable_memory:
            working_context = self.memory.get_working_context(n=3)
            if working_context:
                return f"Contexte récent:\n{working_context}\n\n{query}"
        return query

    def _build_agents_description(self) -> str:
        desc = []
        for name, agent in self.agents.items():
            tool_names = ", ".join([t.name for t in agent.get_tools()])
            desc.append(f"- {name}: {tool_names}")
        return "\n".join(desc)

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
                if plan and self._validate_plan(plan):
                    return plan
                logger.warning(f"Plan invalide, tentative {attempt+1}")
            except Exception as e:
                logger.error(f"Exception génération plan: {e}")
            if attempt < self.max_plan_retries:
                time.sleep(0.5 * (attempt + 1))
        return None

    def _generate_plan(self, query: str) -> Optional[List[Dict]]:
        agents_desc = self._build_agents_description()
        prompt = f"""Planifie: "{query}"
Agents: {agents_desc}
Format JSON: [{{"id":"1","agent":"X","tool":"Y","parameters":{{}},"description":"..."}}]
Ex: [{{"id":"1","agent":"ComputerControlAgent","tool":"open_application","parameters":{{"app_name":"Notes"}},"description":"Ouvre Notes"}}]
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

    # -----------------------------------------------------------------------
    # Interface publique (think)
    # -----------------------------------------------------------------------

    def think(self, query: str, system_prompt: Optional[str] = None,
              allow_web_search: bool = True) -> Tuple[str, float]:
        start = time.time()
        logger.info(f"🧠 think() - Requête: {query[:50]}...")

        paths = self.action_selector.get_paths_for_query(query)
        logger.info(f"⚡ Chemins possibles: {[p[0] for p in paths]}")

        last_error = None
        for path_id, path_func in paths:
            try:
                response = path_func(query)
                duration = time.time() - start
                self.action_selector.record_success(query, path_id, duration)
                record_cortex_step(path_id, duration)
                logger.info(f"✅ Chemin {path_id} réussi en {duration:.3f}s")
                return response, duration
            except Exception as e:
                logger.warning(f"Chemin {path_id} échoué: {e}")
                self.action_selector.record_failure(query, path_id)
                last_error = e

        logger.error(f"Tous les chemins ont échoué: {last_error}")
        response = self._safe_fallback(query)
        duration = time.time() - start
        record_cortex_step("safe_fallback", duration)
        return response, duration

    def stop(self):
        self.predictor.stop()
        self.executor.shutdown()
        logger.info("Cortex arrêté.")