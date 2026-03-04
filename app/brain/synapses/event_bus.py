import threading
import uuid
import time
from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict
from ...utils.logger import get_logger

logger = get_logger(__name__)

class EventBus:
    """
    Bus d'événements asynchrone avec pattern publish/subscribe.
    Permet également les requêtes/réponses avec timeout.
    """

    def __init__(self, max_history: int = 100):
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self.event_history: List[tuple] = []
        self.max_history = max_history
        self._lock = threading.RLock()
        self._response_events: Dict[str, threading.Event] = {}
        self._response_data: Dict[str, Any] = {}

    def publish(self, event_type: str, data: Any = None, source: str = None):
        """
        Publie un événement. Tous les abonnés sont appelés dans des threads séparés.
        """
        with self._lock:
            event_id = str(uuid.uuid4())
            timestamp = time.time()
            logger.debug(f"📢 Événement: {event_type} (id: {event_id})")

            # Historique
            self.event_history.append((timestamp, event_type, data, source))
            if len(self.event_history) > self.max_history:
                self.event_history.pop(0)

            # Appeler les callbacks
            for callback in self.subscribers.get(event_type, []):
                try:
                    # Lancer dans un thread pour ne pas bloquer le publisher
                    threading.Thread(
                        target=self._safe_callback,
                        args=(callback, event_type, data, event_id, source),
                        daemon=True
                    ).start()
                except Exception as e:
                    logger.error(f"Erreur lors du lancement du callback pour {event_type}: {e}")

    def _safe_callback(self, callback: Callable, event_type: str, data: Any, event_id: str, source: str):
        """Exécute un callback en capturant les exceptions."""
        try:
            callback(data, event_id, source)
        except Exception as e:
            logger.error(f"Exception dans le callback de {event_type}: {e}")

    def subscribe(self, event_type: str, callback: Callable):
        """Abonne un callback à un type d'événement."""
        with self._lock:
            if callback not in self.subscribers[event_type]:
                self.subscribers[event_type].append(callback)
                logger.debug(f"📝 Abonnement à {event_type}")

    def unsubscribe(self, event_type: str, callback: Callable):
        """Désabonne un callback."""
        with self._lock:
            if callback in self.subscribers[event_type]:
                self.subscribers[event_type].remove(callback)

    def request(self, request_type: str, data: Any = None, timeout: float = 5.0) -> Optional[Any]:
        """
        Envoie une requête et attend une réponse.
        La réponse doit être publiée sur 'response.{request_type}' avec le même request_id.
        """
        request_id = str(uuid.uuid4())
        response_event = threading.Event()

        def response_handler(response_data, resp_id, source):
            if resp_id == request_id:
                self._response_data[request_id] = response_data
                response_event.set()

        self.subscribe(f"response.{request_type}", response_handler)
        self.publish(f"request.{request_type}", {'request_id': request_id, 'data': data})

        success = response_event.wait(timeout=timeout)
        self.unsubscribe(f"response.{request_type}", response_handler)

        if success:
            return self._response_data.pop(request_id, None)
        else:
            logger.warning(f"Timeout sur requête {request_type} (id: {request_id})")
            return None

    def get_history(self, limit: int = 10) -> List[tuple]:
        """Retourne les derniers événements."""
        with self._lock:
            return self.event_history[-limit:]