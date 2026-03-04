"""
Moteur principal de l'application.
Coordonne le cortex, les services, la mémoire et les agents.
"""

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
from app.actions.system import SystemActions
from app.actions.writer import WriterAgent
from app.actions.router import ActionRouter
from app.core.executor import TaskExecutor
from app.utils.circuit_breaker import CircuitBreaker
from ..utils.logger import logger
from ..utils.metrics import start_metrics_server
from ..utils.memory_monitor import monitor_memory
from ..memory import MemoryService, EpisodicMemory, WorkingMemory, ConsolidationEngine
from ..core.elasticity import ElasticityEngine
from ..agents.profile_agent import ProfileAgent


class LucidEngine:
    def __init__(self, config: Config):
        self.config = config
        self.bus = SynapseBus()
        self.event_bus = EventBus()

        # Démarrer les métriques (optionnel)
        if config.metrics.enabled:
            start_metrics_server(port=config.metrics.port)
            monitor_memory(interval=config.metrics.memory_interval)

        self._init_llm()

        data_dir = Path(config.app.data_dir)
        self.executor = TaskExecutor(max_workers=3, persist_path=data_dir / "tasks.pkl")
        self.prompt_cache = PromptCache(cache_dir=data_dir / "cache", max_size=10000)
        self.ollama_circuit = CircuitBreaker("ollama", failure_threshold=3, recovery_timeout=30)

        # Initialisation de la mémoire
        episodic = EpisodicMemory(
            persist_directory=str(data_dir / "episodic"),
            max_entries=config.memory.max_episodic
        )
        working = WorkingMemory(capacity=config.memory.working_capacity)
        self.memory = MemoryService(episodic, working)

        # Consolidation (optionnelle)
        self.consolidation = ConsolidationEngine(
            episodic,
            interval=config.memory.consolidation_interval
        )
        if config.memory.auto_consolidate:
            self.consolidation.start()

        # Élasticité matérielle (convertir la dataclass en dict)
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
                "web_search": True,  # à ajuster selon besoin
                "api_keys": asdict(config.api_keys),
                "vision": asdict(config.vision),
                "enable_memory": True,
                "enable_elasticity": True,
                "plan_timeout": 30.0,
                "max_plan_retries": 1,
            }
        )

        # ProfileAgent (arrière‑plan)
        self.profile_agent = ProfileAgent(
            llm_service=self.manager,
            bus=self.bus,
            memory_service=self.memory,
            rag_service=self.rag,
            config=asdict(config)  # on passe tout le config en dict
        )
        self.profile_agent.start()

        logger.info("✅ Moteur Lucide initialisé avec mémoire, élasticité et profil")

    def _init_llm(self):
        models_config = {}
        for key, m in self.config.llm.models.items():
            # m est un ModelConfig, on le convertit en dict pour ProviderManager
            models_config[key] = asdict(m)
        self.manager = ProviderManager({
            "host": self.config.llm.host,
            "models": models_config,
            "timeout": self.config.llm.timeout,
            "retry_attempts": self.config.llm.retry_attempts,
            "retry_delay": self.config.llm.retry_delay,
            "keep_alive": self.config.llm.keep_alive,  # ← nouveau paramètre
        })

    def process(self, query: str, system_prompt: Optional[str] = None,
                use_rag: bool = True, allow_web_search: bool = True) -> Tuple[str, float]:
        import time
        start = time.time()
        logger.info(f"⚙️ Engine.process() - Requête: {query[:50]}...")

        rag_context = self.rag.query(query) if use_rag else ""
        full_context = ""
        if rag_context:
            full_context += f"Documents pertinents:\n{rag_context}\n\n"

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

    def index_file(self, path: str) -> bool:
        return self.rag.index_file(path)

    def index_folder(self, path: str) -> int:
        return self.rag.index_folder(path)

    def stop(self):
        self.executor.shutdown()
        self.cortex.stop()
        self.consolidation.stop()
        self.elasticity.stop()
        self.profile_agent.stop()
        logger.info("Moteur arrêté.")