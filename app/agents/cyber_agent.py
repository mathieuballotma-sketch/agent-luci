"""
Agent Cyber - Système immunitaire pour Agent Lucide.
Surveille les erreurs, détecte les anomalies, met en quarantaine les outils défaillants,
conserve une mémoire immunitaire longue et surveille l'homéostasie système.
"""

import asyncio
import hashlib
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
import json

import psutil

from app.agents.base_agent import BaseAgent
from app.utils.logger import logger
from app.utils.metrics import (
    cyber_errors_detected,
    cyber_threats_shared,
    cyber_immunity_updates,
    cyber_quarantine_actions
)


@dataclass
class ThreatSignature:
    """Signature d'une menace (erreur récurrente)."""
    id: str
    pattern: str
    first_seen: float
    last_seen: float
    count: int
    affected_agents: Set[str]
    severity: float  # 0-1
    resolved: bool = False
    quarantined: bool = False
    solution: Optional[str] = None  # description de la solution si connue


class CyberAgent(BaseAgent):
    """
    Agent de cybersécurité interne.
    Surveille les événements d'erreur, détecte les patterns anormaux,
    maintient une base de signatures de menaces, et peut mettre en quarantaine.
    """

    def __init__(self, llm_service, bus, event_bus, config: dict, memory_service=None):
        super().__init__("CyberAgent", llm_service, bus)
        self.event_bus = event_bus
        self.memory = memory_service  # pour la mémoire immunitaire longue

        # Configuration
        self.error_threshold = config.get("cyber_error_threshold", 3)
        self.time_window = config.get("cyber_time_window", 300)
        self.severity_threshold = config.get("cyber_severity_threshold", 0.5)
        self.quarantine_duration = config.get("cyber_quarantine_duration", 3600)  # 1h

        # Base de signatures locales
        self.signatures: Dict[str, ThreatSignature] = {}
        self._lock = threading.RLock()

        # Historique des erreurs pour détection
        self.error_history = deque(maxlen=1000)

        # Quarantaine : outil interdit temporairement
        self.quarantine: Dict[str, float] = {}  # agent:tool -> expiration timestamp

        # Thread de surveillance périodique
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

        # Souscrire aux événements
        self.event_bus.subscribe("tool.error", self._on_tool_error)
        self.event_bus.subscribe("agent.error", self._on_agent_error)
        self.event_bus.subscribe("system.anomaly", self._on_system_anomaly)

        # Charger les signatures historiques depuis la mémoire (si disponible)
        if self.memory:
            self._load_historical_signatures()

        logger.info("🛡️ Agent Cyber initialisé")

    def get_tools(self) -> list:
        return []

    def can_handle(self, query: str) -> bool:
        return False

    async def handle(self, query: str) -> str:
        return "Agent Cyber non destiné à un usage direct."

    # -----------------------------------------------------------------------
    # Gestion des événements
    # -----------------------------------------------------------------------

    def _on_tool_error(self, data: dict, event_id: str, source: str):
        error_msg = data.get("error", "")
        agent = data.get("agent", "unknown")
        tool = data.get("tool", "unknown")
        timestamp = time.time()

        # Vérifier si l'outil est en quarantaine
        key = f"{agent}:{tool}"
        with self._lock:
            if key in self.quarantine and self.quarantine[key] > timestamp:
                logger.debug(f"Outil {key} en quarantaine, erreur ignorée")
                return

        with self._lock:
            self.error_history.append((timestamp, agent, tool, error_msg))
            self._analyze_error(error_msg, agent, tool, timestamp)

        cyber_errors_detected.labels(agent=agent, tool=tool).inc()

    def _on_agent_error(self, data: dict, event_id: str, source: str):
        error_msg = data.get("error", "")
        agent = data.get("agent", source)
        timestamp = time.time()
        with self._lock:
            self.error_history.append((timestamp, agent, "general", error_msg))
            self._analyze_error(error_msg, agent, "general", timestamp)
        cyber_errors_detected.labels(agent=agent, tool="general").inc()

    def _on_system_anomaly(self, data: dict, event_id: str, source: str):
        # Homéostasie : surveiller la charge
        cpu = data.get("cpu", 0)
        mem = data.get("memory", 0)
        if cpu > 80 or mem > 80:
            # Publier un signal de throttling
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(
                    "system.throttle",
                    {"cpu": cpu, "memory": mem, "reason": "high_load"},
                    self.name
                ),
                asyncio.get_event_loop()
            )
            logger.warning(f"⚠️ Charge système élevée: CPU={cpu}%, Mémoire={mem}%")

    # -----------------------------------------------------------------------
    # Analyse et détection
    # -----------------------------------------------------------------------

    def _analyze_error(self, error_msg: str, agent: str, tool: str, timestamp: float):
        normalized = self._normalize_error(error_msg)
        signature_id = hashlib.md5(f"{agent}:{tool}:{normalized}".encode()).hexdigest()

        if signature_id in self.signatures:
            sig = self.signatures[signature_id]
            sig.last_seen = timestamp
            sig.count += 1
            sig.affected_agents.add(agent)
            sig.severity = self._compute_severity(sig)
        else:
            # Nouvelle signature
            sig = ThreatSignature(
                id=signature_id,
                pattern=normalized,
                first_seen=timestamp,
                last_seen=timestamp,
                count=1,
                affected_agents={agent},
                severity=0.1
            )
            self.signatures[signature_id] = sig

        # Vérifier si cette erreur existe dans les archives (mémoire longue)
        if self.memory and sig.count == 1:  # première fois
            self._check_historical_match(normalized, agent, tool, sig)

        # Si le seuil est atteint, déclencher une alerte et éventuellement quarantaine
        if sig.count >= self.error_threshold and sig.severity >= self.severity_threshold:
            self._trigger_alert(sig)
            if sig.severity > 0.8:
                self._quarantine_tool(agent, tool, sig)

    def _normalize_error(self, error_msg: str) -> str:
        import re
        normalized = re.sub(r'\b\d+\b', '<NUM>', error_msg)
        normalized = re.sub(r'/[^\s]+', '<PATH>', normalized)
        normalized = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '<UUID>', normalized)
        return normalized

    def _compute_severity(self, sig: ThreatSignature) -> float:
        now = time.time()
        age = now - sig.first_seen
        recency = (now - sig.last_seen) / 3600  # heures depuis la dernière
        frequency = sig.count / max(age, 1) * 3600  # erreurs par heure
        spread = len(sig.affected_agents) / 5.0  # proportion arbitraire

        severity = min(1.0, (frequency / 10) * 0.4 + (1 / (recency + 1)) * 0.3 + spread * 0.3)
        return severity

    def _trigger_alert(self, sig: ThreatSignature):
        logger.warning(f"🚨 Menace détectée: {sig.pattern} (sévérité {sig.severity:.2f})")
        asyncio.run_coroutine_threadsafe(
            self.event_bus.publish(
                "cyber.threat",
                {
                    "signature_id": sig.id,
                    "pattern": sig.pattern,
                    "severity": sig.severity,
                    "count": sig.count,
                    "affected_agents": list(sig.affected_agents),
                    "solution": sig.solution
                },
                self.name
            ),
            asyncio.get_event_loop()
        )
        cyber_threats_shared.inc()

    def _quarantine_tool(self, agent: str, tool: str, sig: ThreatSignature):
        """Met un outil en quarantaine pour une durée déterminée."""
        key = f"{agent}:{tool}"
        expire = time.time() + self.quarantine_duration
        with self._lock:
            self.quarantine[key] = expire
            sig.quarantined = True
        logger.error(f"⛔ Outil {key} mis en quarantaine jusqu'à {time.ctime(expire)}")
        cyber_quarantine_actions.labels(agent=agent, tool=tool).inc()

        # Publier un événement pour informer les autres agents
        asyncio.run_coroutine_threadsafe(
            self.event_bus.publish(
                "cyber.quarantine",
                {"agent": agent, "tool": tool, "until": expire},
                self.name
            ),
            asyncio.get_event_loop()
        )

    # -----------------------------------------------------------------------
    # Mémoire immunitaire longue (via ChromaDB)
    # -----------------------------------------------------------------------

    def _load_historical_signatures(self):
        """Charge les signatures anciennes depuis la mémoire épisodique."""
        if not self.memory:
            return
        try:
            # On cherche des souvenirs avec le tag "cyber_signature"
            results = self.memory.remember("cyber_signature", n_results=50, min_similarity=0.6)
            for res in results:
                metadata = res.get("metadata", {})
                if metadata.get("type") == "cyber_signature":
                    sig_data = json.loads(metadata.get("data", "{}"))
                    sig = ThreatSignature(
                        id=sig_data["id"],
                        pattern=sig_data["pattern"],
                        first_seen=sig_data["first_seen"],
                        last_seen=sig_data["last_seen"],
                        count=sig_data["count"],
                        affected_agents=set(sig_data["affected_agents"]),
                        severity=sig_data["severity"],
                        resolved=True,  # archivée
                        solution=sig_data.get("solution")
                    )
                    with self._lock:
                        self.signatures[sig.id] = sig
            logger.info(f"📚 Chargé {len(results)} signatures historiques")
        except Exception as e:
            logger.error(f"Erreur chargement historique: {e}")

    def _check_historical_match(self, normalized: str, agent: str, tool: str, current_sig: ThreatSignature):
        """Vérifie si une erreur actuelle correspond à une signature archivée."""
        if not self.memory:
            return
        try:
            # Recherche dans la mémoire épisodique des signatures similaires
            results = self.memory.remember(normalized, n_results=3, min_similarity=0.8)
            for res in results:
                metadata = res.get("metadata", {})
                if metadata.get("type") == "cyber_signature":
                    old_sig = json.loads(metadata.get("data", "{}"))
                    if old_sig.get("pattern") == normalized:
                        current_sig.solution = old_sig.get("solution", "Solution archivée disponible")
                        logger.info(f"🔁 Correspondance historique trouvée pour {normalized}")
                        break
        except Exception as e:
            logger.error(f"Erreur recherche historique: {e}")

    def _archive_signature(self, sig: ThreatSignature):
        """Stocke une signature dans la mémoire épisodique pour référence future."""
        if not self.memory:
            return
        try:
            data = {
                "id": sig.id,
                "pattern": sig.pattern,
                "first_seen": sig.first_seen,
                "last_seen": sig.last_seen,
                "count": sig.count,
                "affected_agents": list(sig.affected_agents),
                "severity": sig.severity,
                "solution": sig.solution or "Inconnue"
            }
            self.memory.add_episode(
                query=f"cyber_signature:{sig.id}",
                response=json.dumps(data),
                metadata={"type": "cyber_signature", "pattern": sig.pattern}
            )
        except Exception as e:
            logger.error(f"Erreur archivage signature: {e}")

    # -----------------------------------------------------------------------
    # Boucle de surveillance périodique
    # -----------------------------------------------------------------------

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            time.sleep(30)  # toutes les 30 secondes
            try:
                self._cleanup_old_signatures()
                self._detect_emerging_patterns()
                self._check_system_health()
            except Exception as e:
                logger.error(f"Erreur dans la boucle Cyber: {e}")

    def _cleanup_old_signatures(self):
        now = time.time()
        with self._lock:
            to_archive = []
            to_delete = []
            for sig_id, sig in self.signatures.items():
                if now - sig.last_seen > 86400:  # 24h sans activité
                    if sig.count >= self.error_threshold:
                        # Archivage si significatif
                        self._archive_signature(sig)
                        to_archive.append(sig_id)
                    else:
                        to_delete.append(sig_id)
                elif sig.resolved and now - sig.last_seen > 3600:
                    to_delete.append(sig_id)
            for sig_id in to_delete:
                del self.signatures[sig_id]
            if to_archive:
                logger.debug(f"Archivage de {len(to_archive)} signatures")
            if to_delete:
                logger.debug(f"Nettoyage de {len(to_delete)} signatures obsolètes")

    def _detect_emerging_patterns(self):
        now = time.time()
        recent = [e for e in self.error_history if now - e[0] < 300]
        if len(recent) < 5:
            return

        counter = defaultdict(int)
        for _, agent, tool, err in recent:
            key = f"{agent}:{tool}"
            counter[key] += 1

        for key, count in counter.items():
            if count > self.error_threshold:
                agent, tool = key.split(":", 1)
                found = False
                for sig in self.signatures.values():
                    if agent in sig.affected_agents and sig.pattern in " ".join([e[3] for e in recent]):
                        found = True
                        break
                if not found:
                    sig = ThreatSignature(
                        id=hashlib.md5(f"emerging:{key}".encode()).hexdigest(),
                        pattern=f"Émergence d'erreurs sur {agent}/{tool}",
                        first_seen=now,
                        last_seen=now,
                        count=count,
                        affected_agents={agent},
                        severity=0.6
                    )
                    with self._lock:
                        self.signatures[sig.id] = sig
                    self._trigger_alert(sig)

    def _check_system_health(self):
        """Surveille la santé système et publie des anomalies."""
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent
        if cpu > 70 or mem > 80:
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(
                    "system.anomaly",
                    {"cpu": cpu, "memory": mem},
                    self.name
                ),
                asyncio.get_event_loop()
            )

    # -----------------------------------------------------------------------
    # Interface publique
    # -----------------------------------------------------------------------

    def get_threats(self) -> List[Dict]:
        with self._lock:
            return [
                {
                    "id": sig.id,
                    "pattern": sig.pattern,
                    "severity": sig.severity,
                    "count": sig.count,
                    "affected_agents": list(sig.affected_agents),
                    "last_seen": sig.last_seen,
                    "quarantined": sig.quarantined
                }
                for sig in self.signatures.values()
                if not sig.resolved and sig.severity >= self.severity_threshold
            ]

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "total_signatures": len(self.signatures),
                "active_threats": len([s for s in self.signatures.values() if not s.resolved]),
                "errors_tracked": len(self.error_history),
                "quarantine_count": len(self.quarantine)
            }

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Agent Cyber arrêté.")