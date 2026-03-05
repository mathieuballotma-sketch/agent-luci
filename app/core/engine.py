"""
Moteur principal de l'application.
Coordonne le cortex, les services, la mémoire et les agents.
Intègre désormais l'agent Cyber.
"""

import asyncio
import threading
import time
from typing import Optional, Tuple
from pathlib import Path
from dataclasses import asdict

from ..core.config import Config
from ..providers.manager import ProviderManager
from app.brain.cortex import FrontalCortex
from app.brain.synapses.bus import SynapseBus
from app.brain.synapses.event_bus import EventBus
from app.services.rag import RAGService
from app.services.prompt_cache import PromptCache
from app.services.scheduler_service import SchedulerService
from app.actions.system import SystemActions
from app.actions.writer import WriterAgent
from app.actions.router import ActionRouter
from app.core.executor import TaskExecutor
from app.utils.circuit_breaker import CircuitBreaker
from ..utils.logger import logger
from ..utils.metrics import start_metrics_server, strategist_suggestions_total
from ..utils.memory_monitor import monitor_memory
from ..memory import MemoryService, EpisodicMemory, WorkingMemory, ConsolidationEngine
from ..core.elasticity import ElasticityEngine
from ..agents.profile_agent import ProfileAgent
from ..agents.strategist_agent import StrategistAgent
from ..agents.cyber_agent import CyberAgent


class LucidEngine:
    def __init__(self, config: Config):
        self.config = config
        self.bus = SynapseBus()
        self.event_bus = EventBus()

        if config.metrics.enabled:
            start_metrics_server(port=config.metrics.port)
            monitor_memory(interval=config.metrics.memory_interval)

        self._init_llm()

        data_dir = Path(config.app.data_dir)
        self.executor = TaskExecutor(max_workers=3, persist_path=data_dir / "tasks.pkl")
        self.prompt_cache = PromptCache(cache_dir=data_dir / "cache", max_size=10000)
        self.ollama_circuit = CircuitBreaker("ollama", failure_threshold=3, recovery_timeout=30)

        # Mémoire
        episodic = EpisodicMemory(
            persist_directory=str(data_dir / "episodic"),
            max_entries=config.memory.max_episodic
        )
        working = WorkingMemory(capacity=config.memory.working_capacity)
        self.memory = MemoryService(episodic, working)

        # Consolidation
        self.consolidation = ConsolidationEngine(
            episodic,
            interval=config.memory.consolidation_interval
        )
        if config.memory.auto_consolidate:
            self.consolidation.start()

        # Élasticité
        self.elasticity = ElasticityEngine(asdict(config.elasticity))
        self.elasticity.start()

        # RAG
        self.rag = RAGService(config.rag)

        # Actions système
        self.system_actions = SystemActions()
        self.writer_agent = WriterAgent(str(config.actions.word_output_dir))
        self.action_router = ActionRouter(self.system_actions, self.writer_agent)

        # Cortex
        self.cortex = FrontalCortex(
            manager=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            prompt_cache=self.prompt_cache,
            memory_service=self.memory,
            elasticity_engine=self.elasticity,
            config={
                "web_search": True,
                "api_keys": asdict(config.api_keys),
                "vision": asdict(config.vision),
                "enable_memory": True,
                "enable_elasticity": True,
                "plan_timeout": 30.0,
                "max_plan_retries": 1,
            }
        )

        # ProfileAgent
        self.profile_agent = ProfileAgent(
            llm_service=self.manager,
            bus=self.bus,
            memory_service=self.memory,
            rag_service=self.rag,
            config=asdict(config)
        )
        self.profile_agent.start()

        # Scheduler et Strategist
        self.scheduler = SchedulerService()
        self.strategist = StrategistAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            memory_service=self.memory,
            config=asdict(config)
        )
        self.scheduler.start()
        self.scheduler.add_cron_job(
            func=self.strategist.run_periodic_review,
            cron_expr="0 * * * *",
            job_id="strategist_review"
        )

        # Agent Cyber
        self.cyber_agent = CyberAgent(
            llm_service=self.manager,
            bus=self.bus,
            event_bus=self.event_bus,
            config=asdict(config),
            memory_service=self.memory
        )
        # On connecte l'event_bus aux agents (pour la publication d'erreurs)
        for agent in self.cortex.agents.values():
            agent.event_bus = self.event_bus
        # Souscrire aux suggestions
        self.event_bus.subscribe("strategist.suggestion", self._handle_suggestion)

        logger.info("✅ Moteur Lucide initialisé avec mémoire, élasticité, profil, scheduler, stratège et cyber")

    def _init_llm(self):
        models_config = {}
        for key, m in self.config.llm.models.items():
            models_config[key] = asdict(m)
        self.manager = ProviderManager({
            "host": self.config.llm.host,
            "models": models_config,
            "timeout": self.config.llm.timeout,
            "retry_attempts": self.config.llm.retry_attempts,
            "retry_delay": self.config.llm.retry_delay,
            "keep_alive": self.config.llm.keep_alive,
        })

    def process(self, query: str, system_prompt: Optional[str] = None,
                use_rag: bool = True, allow_web_search: bool = True) -> Tuple[str, float]:
        start = time.time()
        logger.info(f"⚙️ Engine.process() - Requête: {query[:50]}...")

        rag_context = self.rag.query(query) if use_rag else ""

        try:
            raw_response, _ = self.ollama_circuit.call(
                lambda: self.cortex.think(
                    query,
                    system_prompt=system_prompt,
                    allow_web_search=allow_web_search
                )
            )
        except Exception as e:
            logger.error(f"Erreur après circuit breaker: {e}")
            return f"Erreur de communication avec le LLM: {e}", time.time() - start

        action_executed, final_response = self.action_router.parse_and_execute(raw_response)

        latency = time.time() - start
        if action_executed:
            logger.info(f"Action exécutée en {latency:.2f}s")
        else:
            logger.info(f"Réponse générée en {latency:.2f}s")

        return final_response, latency

    async def process_async(self, query: str, system_prompt: Optional[str] = None,
                            use_rag: bool = True, allow_web_search: bool = True) -> Tuple[str, float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.process, query, system_prompt, use_rag, allow_web_search)

    def index_file(self, path: str) -> bool:
        return self.rag.index_file(path)

    def index_folder(self, path: str) -> int:
        return self.rag.index_folder(path)

    def _handle_suggestion(self, data, event_id, source):
        logger.info(f"💡 Réception suggestion: {data.get('title', 'sans titre')}")
        cron = data.get("cron_expression")
        query = data.get("query")
        if cron and query:
            try:
                from croniter import croniter
                if not croniter.is_valid(cron):
                    logger.warning(f"Expression cron invalide: {cron}")
                    return
            except ImportError:
                pass
            self.scheduler.add_cron_job(
                func=self._execute_scheduled_query,
                cron_expr=cron,
                job_id=f"auto_{data.get('title', 'task')[:20]}",
                kwargs={"query": query}
            )
            logger.info(f"📅 Tâche automatique ajoutée: {data.get('title')}")
        else:
            logger.debug("Suggestion sans cron/query, ignorée")

    async def _execute_scheduled_query(self, query: str):
        logger.info(f"⏰ Exécution programmée: {query}")
        try:
            response, latency = await self.process_async(query, use_rag=False)
            logger.info(f"✅ Résultat: {response[:100]}... (latence {latency:.2f}s)")
        except Exception as e:
            logger.error(f"❌ Erreur exécution programmée: {e}")

    def stop(self):
        self.executor.shutdown()
        self.cortex.stop()
        self.consolidation.stop()
        self.elasticity.stop()
        self.profile_agent.stop()
        if hasattr(self, 'scheduler'):
            self.scheduler.stop()
        if hasattr(self, 'cyber_agent'):
            self.cyber_agent.stop()
        logger.info("Moteur arrêté.")