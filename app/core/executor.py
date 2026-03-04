"""
Gestionnaire de tâches asynchrones avec dépendances, persistance et métriques.
Permet d'exécuter des tâches en parallèle avec gestion des priorités et des dépendances.
"""

import queue
import threading
import time
import pickle
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from collections import defaultdict
from ..utils.logger import logger
from ..utils.metrics import (
    active_tasks,
    task_queue_size,
    tasks_completed_total,
    tasks_failed_total,
    tasks_cancelled_total,
    task_execution_duration,
    set_active_tasks,
    set_task_queue_size,
)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class Task:
    id: str
    name: str
    func: Optional[Callable] = None
    args: tuple = ()
    kwargs: dict = None
    priority: int = 0
    dependencies: List[str] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = None
    created_at: float = None
    started_at: float = None
    completed_at: float = None
    progress: float = 0.0
    progress_message: str = ""
    user_id: str = "default"
    metadata: dict = None


class TaskExecutor:
    def __init__(self, max_workers: int = 3, persist_path: Path = None, retention_seconds: int = 3600):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.task_queue = queue.PriorityQueue()
        self.tasks: Dict[str, Task] = {}
        self.futures: Dict[str, Future] = {}
        self.running = True
        self.persist_path = persist_path
        self.persist_interval = 60
        self.last_persist = time.time()
        self.retention_seconds = retention_seconds
        self.metrics = {
            'total_submitted': 0,
            'total_completed': 0,
            'total_failed': 0,
            'total_cancelled': 0,
            'avg_wait_time': 0.0,
            'avg_execution_time': 0.0,
            'queue_size_history': []
        }
        self._lock = threading.RLock()
        self._load_persisted_tasks()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        if self.persist_path is not None:
            self._persist_thread = threading.Thread(target=self._persist_loop, daemon=True)
            self._persist_thread.start()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        logger.info(f"✅ TaskExecutor démarré avec {max_workers} workers, {len(self.tasks)} tâches restaurées, rétention={retention_seconds}s")

    def _load_persisted_tasks(self):
        if self.persist_path and self.persist_path.exists():
            try:
                with open(self.persist_path, 'rb') as f:
                    data = pickle.load(f)
                    tasks_dict = data.get('tasks', {})
                    for task_id, task_dict in tasks_dict.items():
                        task_dict['func'] = None
                        task = Task(**task_dict)
                        self.tasks[task_id] = task
                        self.futures[task_id] = Future()
                        if task.status == TaskStatus.COMPLETED:
                            self.futures[task_id].set_result(task.result)
                        elif task.status == TaskStatus.FAILED:
                            self.futures[task_id].set_exception(Exception(task.error))
                        elif task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                            task.status = TaskStatus.PENDING
                            self.task_queue.put((-task.priority, task_id))
                    self.metrics = data.get('metrics', self.metrics)
                    logger.info(f"📦 {len(self.tasks)} tâches restaurées")
            except Exception as e:
                logger.error(f"Erreur restauration tâches: {e}")

    def _persist_tasks(self):
        try:
            serializable_tasks = {}
            for task_id, task in self.tasks.items():
                task_dict = asdict(task)
                task_dict.pop('func', None)
                serializable_tasks[task_id] = task_dict
            data = {'tasks': serializable_tasks, 'metrics': self.metrics, 'timestamp': time.time()}
            with open(self.persist_path, 'wb') as f:
                pickle.dump(data, f)
            self.last_persist = time.time()
        except Exception as e:
            logger.error(f"Erreur persistance tâches: {e}")

    def _persist_loop(self):
        while self.running and self.persist_path is not None:
            time.sleep(self.persist_interval)
            self._persist_tasks()

    def _cleanup_loop(self):
        while self.running:
            time.sleep(60)
            self._cleanup_old_tasks()

    def _cleanup_old_tasks(self):
        with self._lock:
            now = time.time()
            to_delete = []
            for task_id, task in self.tasks.items():
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    if task.completed_at and now - task.completed_at > self.retention_seconds:
                        to_delete.append(task_id)
                        self.futures.pop(task_id, None)
            for task_id in to_delete:
                del self.tasks[task_id]
            if to_delete:
                logger.debug(f"🧹 Nettoyage de {len(to_delete)} anciennes tâches")

    def submit(self, task: Task, priority: Optional[int] = None) -> str:
        """
        Soumet une tâche avec une priorité optionnelle.
        Si priority est fourni, il écrase la priorité de la tâche.
        """
        with self._lock:
            task.id = task.id or str(uuid.uuid4())
            if priority is not None:
                task.priority = priority
            task.created_at = task.created_at or time.time()
            task.status = TaskStatus.PENDING
            if task.kwargs is None:
                task.kwargs = {}
            self.tasks[task.id] = task
            self.futures[task.id] = Future()
            self.task_queue.put((-task.priority, task.id))
            self.metrics['total_submitted'] += 1
            set_task_queue_size(self.task_queue.qsize())
            logger.debug(f"📤 Tâche soumise: {task.name} (id: {task.id}, priorité: {task.priority})")
        return task.id

    def submit_batch(self, tasks: List[Task]) -> List[str]:
        return [self.submit(task) for task in tasks]

    def _worker_loop(self):
        while self.running:
            try:
                qsize = self.task_queue.qsize()
                set_task_queue_size(qsize)
                self.metrics['queue_size_history'].append(qsize)
                if len(self.metrics['queue_size_history']) > 100:
                    self.metrics['queue_size_history'].pop(0)

                priority, task_id = self.task_queue.get(timeout=1)
                task = self.tasks.get(task_id)
                future = self.futures.get(task_id)
                if not task or task.status == TaskStatus.CANCELLED:
                    if future and not future.done():
                        future.set_exception(Exception("Tâche annulée"))
                    continue
                if task.status == TaskStatus.PAUSED:
                    self.task_queue.put((priority, task_id))
                    time.sleep(0.5)
                    continue
                if not self._check_dependencies(task):
                    self.task_queue.put((priority, task_id))
                    time.sleep(0.2)
                    continue

                wait_time = time.time() - task.created_at
                task.status = TaskStatus.RUNNING
                task.started_at = time.time()
                self.metrics['avg_wait_time'] = (
                    (self.metrics['avg_wait_time'] * self.metrics['total_completed'] + wait_time) /
                    (self.metrics['total_completed'] + 1)
                )

                dep_results = []
                if task.dependencies:
                    for dep_id in task.dependencies:
                        dep_task = self.tasks.get(dep_id)
                        if dep_task and dep_task.status == TaskStatus.COMPLETED:
                            dep_results.append(dep_task.result)
                        else:
                            dep_results.append(None)

                all_args = tuple(dep_results) + task.args
                self.executor.submit(self._execute_task, task, future, *all_args, **task.kwargs)

                set_active_tasks(len(self.futures))

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Erreur dans worker loop: {e}")

    def _execute_task(self, task: Task, future: Future, *args, **kwargs):
        try:
            if 'progress_callback' in kwargs:
                kwargs['progress_callback'] = lambda p, m: self._update_progress(task.id, p, m)
            result = task.func(*args, **kwargs)
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            execution_time = task.completed_at - task.started_at
            with self._lock:
                self.metrics['total_completed'] += 1
                self.metrics['avg_execution_time'] = (
                    (self.metrics['avg_execution_time'] * (self.metrics['total_completed'] - 1) + execution_time) /
                    self.metrics['total_completed']
                )
            tasks_completed_total.labels(task_name=task.name).inc()
            task_execution_duration.labels(task_name=task.name).observe(execution_time)
            future.set_result(result)
            logger.info(f"✅ Tâche terminée: {task.name} ({execution_time:.2f}s)")
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = time.time()
            with self._lock:
                self.metrics['total_failed'] += 1
            tasks_failed_total.labels(task_name=task.name).inc()
            future.set_exception(e)
            logger.error(f"❌ Tâche échouée: {task.name} - {e}")

    def _update_progress(self, task_id: str, progress: float, message: str):
        task = self.tasks.get(task_id)
        if task:
            task.progress = progress
            task.progress_message = message

    def _check_dependencies(self, task: Task) -> bool:
        if not task.dependencies:
            return True
        for dep_id in task.dependencies:
            dep_task = self.tasks.get(dep_id)
            if not dep_task:
                logger.warning(f"Dépendance {dep_id} introuvable pour {task.id}")
                continue
            if dep_task.status == TaskStatus.FAILED:
                task.status = TaskStatus.FAILED
                task.error = f"Dépendance {dep_id} a échoué"
                tasks_failed_total.labels(task_name=task.name).inc()
                future = self.futures.get(task.id)
                if future and not future.done():
                    future.set_exception(Exception(task.error))
                return False
            if dep_task.status != TaskStatus.COMPLETED:
                return False
        return True

    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        task = self.tasks.get(task_id)
        return task.status if task else None

    def get_task_result(self, task_id: str, timeout: float = None) -> Any:
        future = self.futures.get(task_id)
        if not future:
            raise Exception(f"Tâche {task_id} introuvable")
        return future.result(timeout=timeout)

    def get_future(self, task_id: str) -> Optional[Future]:
        with self._lock:
            return self.futures.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            future = self.futures.get(task_id)
            if task and task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
                self.metrics['total_cancelled'] += 1
                tasks_cancelled_total.labels(task_name=task.name).inc()
                if future and not future.done():
                    future.set_exception(Exception("Tâche annulée"))
                return True
            return False

    def pause_task(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if task and task.status == TaskStatus.PENDING:
                task.status = TaskStatus.PAUSED
                return True
            return False

    def resume_task(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if task and task.status == TaskStatus.PAUSED:
                task.status = TaskStatus.PENDING
                self.task_queue.put((-task.priority, task_id))
                return True
            return False

    def get_queue_stats(self) -> dict:
        with self._lock:
            return {
                'pending': sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING),
                'running': sum(1 for t in self.tasks.values() if t.status == TaskStatus.RUNNING),
                'completed': sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED),
                'failed': sum(1 for t in self.tasks.values() if t.status == TaskStatus.FAILED),
                'cancelled': sum(1 for t in self.tasks.values() if t.status == TaskStatus.CANCELLED),
                'paused': sum(1 for t in self.tasks.values() if t.status == TaskStatus.PAUSED),
                'queue_size': self.task_queue.qsize(),
            }

    def get_stats(self) -> dict:
        with self._lock:
            return {
                'metrics': self.metrics.copy(),
                'queue': self.get_queue_stats(),
                'workers': self.max_workers,
                'persist_last': self.last_persist
            }

    def shutdown(self):
        self.running = False
        self.executor.shutdown(wait=True)
        if self.persist_path is not None:
            self._persist_tasks()
        logger.info("TaskExecutor arrêté")