"""
Service de planification de tâches cron asynchrones.
Utilise APScheduler avec le scheduler asyncio dans un thread dédié.
"""

import asyncio
import threading
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import Callable, Coroutine, Any, Optional

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service de planification de tâches cron asynchrones."""

    def __init__(self):
        self.scheduler = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready_event = threading.Event()  # Pour signaler que la boucle est prête
        self.tasks = {}

    def start(self):
        """Démarre le scheduler dans un thread séparé avec sa propre boucle."""
        if self._thread is not None:
            logger.warning("Scheduler déjà démarré.")
            return

        self._ready_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        # Attendre que la boucle soit prête
        self._ready_event.wait(timeout=5)
        logger.info("✅ SchedulerService démarré dans un thread dédié")

    def _run_loop(self):
        """Point d'entrée du thread : crée la boucle et démarre le scheduler."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.scheduler = AsyncIOScheduler(event_loop=self._loop)
        self.scheduler.start()
        self._ready_event.set()  # Signal que le scheduler est démarré
        try:
            self._loop.run_forever()
        except Exception as e:
            logger.error(f"Erreur dans la boucle du scheduler: {e}")
        finally:
            self._loop.close()
            logger.info("Boucle du scheduler terminée.")

    def stop(self):
        """Arrête proprement le scheduler et la boucle."""
        if self._loop and self._thread and self._thread.is_alive():
            # Shutdown du scheduler dans le thread de la boucle
            future = asyncio.run_coroutine_threadsafe(self._shutdown_scheduler(), self._loop)
            future.result(timeout=5)

            # Arrêter la boucle
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            logger.info("SchedulerService arrêté.")

    async def _shutdown_scheduler(self):
        """Coroutine pour arrêter le scheduler proprement."""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("Scheduler APScheduler arrêté.")

    def add_cron_job(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        cron_expr: str,
        job_id: str,
        args: list = None,
        kwargs: dict = None
    ):
        """
        Ajoute une tâche asynchrone avec une expression cron.
        Cette méthode est thread-safe (utilise call_soon_threadsafe).
        """
        if not self._loop or not self.scheduler:
            raise RuntimeError("Scheduler non démarré. Appelez start() d'abord.")

        trigger = CronTrigger.from_crontab(cron_expr)
        # On doit ajouter le job dans le thread de la boucle
        asyncio.run_coroutine_threadsafe(
            self._add_job_async(func, trigger, job_id, args, kwargs),
            self._loop
        )
        logger.info(f"📅 Tâche cron ajoutée: {job_id} ({cron_expr})")

    async def _add_job_async(self, func, trigger, job_id, args, kwargs):
        """Coroutine interne pour ajouter un job."""
        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True
        )