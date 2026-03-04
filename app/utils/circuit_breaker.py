import time
import threading
from enum import Enum
from typing import Callable, Optional, Any
from dataclasses import dataclass, field
from collections import deque
from .logger import get_logger

logger = get_logger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class CircuitMetrics:
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    fallback_used: int = 0
    open_count: int = 0
    last_open_time: float = 0.0
    last_failure_time: float = 0.0
    consecutive_successes: int = 0
    # Garder un historique des temps de réponse (max 100)
    response_times: deque = field(default_factory=lambda: deque(maxlen=100))

class CircuitBreaker:
    """
    Implémentation du pattern Circuit Breaker pour protéger les appels à des services externes.
    """
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_success_threshold: int = 2
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_success_threshold = half_open_success_threshold

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_successes = 0
        self.last_failure_time = 0.0
        self.last_state_change = time.time()
        self.metrics = CircuitMetrics()
        self._lock = threading.RLock()
        logger.info(f"🔌 CircuitBreaker '{name}' initialisé")

    def call(self, func: Callable, fallback: Optional[Callable] = None, *args, **kwargs) -> Any:
        """
        Exécute la fonction avec protection du circuit breaker.
        Si le circuit est ouvert, utilise le fallback si fourni, sinon lève une exception.
        """
        start_time = time.time()
        with self._lock:
            self.metrics.total_calls += 1

            # Vérifier si on peut passer en half-open
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    logger.info(f"🔄 Circuit '{self.name}' passe en HALF_OPEN après timeout")
                    self._transition_to(CircuitState.HALF_OPEN)
                    self.half_open_successes = 0
                else:
                    self._record_fallback()
                    if fallback:
                        logger.warning(f"⚠️ Circuit '{self.name}' OPEN, utilisation du fallback")
                        return self._execute_fallback(fallback, *args, **kwargs)
                    else:
                        raise Exception(f"Circuit '{self.name}' is OPEN (recovery in {self.recovery_timeout - (time.time() - self.last_failure_time):.1f}s)")

            elif self.state == CircuitState.HALF_OPEN:
                # En half-open, on laisse passer un certain nombre de requêtes
                if self.half_open_successes >= self.half_open_success_threshold:
                    self._record_fallback()
                    if fallback:
                        return self._execute_fallback(fallback, *args, **kwargs)
                    else:
                        raise Exception(f"Circuit '{self.name}' is HALF_OPEN (too many concurrent requests)")

        # Exécution de la fonction
        try:
            result = func(*args, **kwargs)
            with self._lock:
                resp_time = time.time() - start_time
                self.metrics.response_times.append(resp_time)
                self.metrics.successful_calls += 1
                self.metrics.consecutive_successes += 1

                if self.state == CircuitState.HALF_OPEN:
                    self.half_open_successes += 1
                    if self.half_open_successes >= self.half_open_success_threshold:
                        logger.info(f"✅ Circuit '{self.name}' refermé après {self.half_open_successes} succès consécutifs")
                        self._transition_to(CircuitState.CLOSED)
                        self.failure_count = 0
                elif self.state == CircuitState.CLOSED:
                    self.failure_count = 0  # Réinitialiser les échecs après un succès
            return result

        except Exception as e:
            with self._lock:
                resp_time = time.time() - start_time
                self.metrics.response_times.append(resp_time)
                self.metrics.failed_calls += 1
                self.metrics.consecutive_successes = 0
                self.last_failure_time = time.time()

                if self.state == CircuitState.HALF_OPEN:
                    logger.warning(f"❌ Échec en HALF_OPEN pour '{self.name}', retour à OPEN")
                    self._transition_to(CircuitState.OPEN)
                elif self.state == CircuitState.CLOSED:
                    self.failure_count += 1
                    if self.failure_count >= self.failure_threshold:
                        logger.warning(f"🔌 Circuit '{self.name}' ouvert après {self.failure_count} échecs consécutifs")
                        self._transition_to(CircuitState.OPEN)
                        self.metrics.open_count += 1

            if fallback:
                self._record_fallback()
                logger.info(f"🔄 Utilisation du fallback pour '{self.name}' après échec")
                return self._execute_fallback(fallback, *args, **kwargs)
            raise e

    def _transition_to(self, new_state: CircuitState):
        """Change l'état et enregistre le moment."""
        self.state = new_state
        self.last_state_change = time.time()
        if new_state == CircuitState.OPEN:
            self.metrics.last_open_time = time.time()

    def _record_fallback(self):
        with self._lock:
            self.metrics.fallback_used += 1

    def _execute_fallback(self, fallback: Callable, *args, **kwargs) -> Any:
        try:
            return fallback(*args, **kwargs)
        except Exception as e:
            logger.error(f"❌ Fallback également échoué pour '{self.name}': {e}")
            raise e

    def get_health_status(self) -> dict:
        """Retourne un rapport détaillé de l'état du circuit."""
        with self._lock:
            total = self.metrics.total_calls
            success_rate = (self.metrics.successful_calls / total * 100) if total else 0.0
            avg_resp = sum(self.metrics.response_times) / len(self.metrics.response_times) if self.metrics.response_times else 0.0
            time_in_state = time.time() - self.last_state_change
            recovery_in = max(0.0, self.recovery_timeout - (time.time() - self.last_failure_time)) if self.state == CircuitState.OPEN else 0.0

            return {
                'name': self.name,
                'state': self.state.value,
                'time_in_state': f"{time_in_state:.1f}s",
                'failure_count': self.failure_count,
                'success_rate': f"{success_rate:.1f}%",
                'avg_response_time': f"{avg_resp*1000:.1f}ms",
                'consecutive_successes': self.metrics.consecutive_successes,
                'metrics': {
                    'total_calls': self.metrics.total_calls,
                    'successful_calls': self.metrics.successful_calls,
                    'failed_calls': self.metrics.failed_calls,
                    'fallback_used': self.metrics.fallback_used,
                    'open_count': self.metrics.open_count,
                },
                'recovery_in': f"{recovery_in:.1f}s"
            }

    def reset(self):
        """Réinitialise manuellement le circuit."""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.half_open_successes = 0
            self.metrics.consecutive_successes = 0
            logger.info(f"🔄 Circuit '{self.name}' réinitialisé manuellement")