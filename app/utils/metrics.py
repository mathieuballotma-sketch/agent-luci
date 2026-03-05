"""
Module de métriques Prometheus pour Agent Lucide.
Expose des métriques sur les requêtes LLM, le cache, les erreurs, etc.
"""

from prometheus_client import Counter, Histogram, Gauge, start_http_server
import threading
import time
from ..utils.logger import logger

# Métriques LLM
llm_requests_total = Counter(
    'llm_requests_total',
    'Total des requêtes LLM',
    ['model', 'status']
)

llm_request_duration_seconds = Histogram(
    'llm_request_duration_seconds',
    'Durée des requêtes LLM',
    ['model'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
)

# Métriques des outils
tool_execution_duration = Histogram(
    'tool_execution_duration_seconds',
    'Durée d exécution des outils',
    ['agent', 'tool'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
)

tool_execution_errors = Counter(
    'tool_execution_errors_total',
    'Nombre d erreurs d exécution des outils',
    ['agent', 'tool']
)

# Métriques du cache
cache_hits = Counter(
    'cache_hits_total',
    'Nombre de hits dans le cache',
    ['cache_type']
)

cache_misses = Counter(
    'cache_misses_total',
    'Nombre de misses dans le cache',
    ['cache_type']
)

plan_cache_hits = Counter(
    'plan_cache_hits_total',
    'Nombre de plans trouvés en cache',
    ['cache_type']
)

plan_cache_misses = Counter(
    'plan_cache_misses_total',
    'Nombre de plans non trouvés en cache',
    ['cache_type']
)

planning_duration = Histogram(
    'planning_duration_seconds',
    'Durée de génération des plans',
    buckets=(0.5, 1.0, 2.0, 3.0, 5.0, 10.0)
)

# Métriques système
system_load_cpu = Gauge(
    'system_load_cpu_percent',
    'Charge CPU actuelle (moyenne sur 2s)'
)

system_load_memory = Gauge(
    'system_load_memory_percent',
    'Utilisation mémoire en pourcentage'
)

system_load_battery = Gauge(
    'system_load_battery_percent',
    'Niveau de batterie (si disponible)'
)

system_thermal_pressure = Gauge(
    'system_thermal_pressure',
    'Pression thermique (0-3)'
)

# Métriques du TaskExecutor
active_tasks = Gauge(
    'active_tasks',
    'Nombre de tâches en cours dans le TaskExecutor'
)

task_queue_size = Gauge(
    'task_queue_size',
    'Nombre de tâches en attente dans le TaskExecutor'
)

tasks_completed_total = Counter(
    'tasks_completed_total',
    'Nombre total de tâches terminées avec succès',
    ['task_name']
)

tasks_failed_total = Counter(
    'tasks_failed_total',
    'Nombre total de tâches ayant échoué',
    ['task_name']
)

tasks_cancelled_total = Counter(
    'tasks_cancelled_total',
    'Nombre total de tâches annulées',
    ['task_name']
)

task_execution_duration = Histogram(
    'task_execution_duration_seconds',
    'Durée d exécution des tâches (TaskExecutor)',
    ['task_name'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

# Mémoire processus
memory_usage_bytes = Gauge(
    'memory_usage_bytes',
    'Utilisation mémoire du processus'
)

# Métriques de mémoire de travail
working_memory_size = Gauge(
    'working_memory_size',
    'Nombre d éléments dans la mémoire de travail'
)

# Métriques du stratège
strategist_suggestions_total = Counter(
    'strategist_suggestions_total',
    'Nombre total de suggestions générées par le stratège',
    ['category']
)

# Métriques des étapes du cortex
cortex_step_duration = Histogram(
    'cortex_step_duration_seconds',
    'Durée de chaque étape du cortex',
    ['step'],
    buckets=(0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
)

# Métriques de l'agent cyber
cyber_errors_detected = Counter(
    'cyber_errors_detected_total',
    'Nombre d erreurs détectées par l agent cyber',
    ['agent', 'tool']
)

cyber_threats_shared = Counter(
    'cyber_threats_shared_total',
    'Nombre de menaces partagées avec le réseau'
)

cyber_immunity_updates = Counter(
    'cyber_immunity_updates_total',
    'Nombre de mises à jour d immunité reçues du réseau'
)

cyber_quarantine_actions = Counter(
    'cyber_quarantine_actions_total',
    'Nombre de mises en quarantaine d outils',
    ['agent', 'tool']
)

# Thread pour le serveur Prometheus
_metrics_server_thread = None


def start_metrics_server(port: int = 8001):
    global _metrics_server_thread
    if _metrics_server_thread is not None:
        logger.warning("Serveur de métriques déjà démarré.")
        return

    def run_server():
        try:
            start_http_server(port)
            logger.info(f"📊 Serveur de métriques Prometheus démarré sur le port {port}")
            while True:
                time.sleep(3600)
        except Exception as e:
            logger.error(f"Erreur lors du démarrage du serveur de métriques: {e}")

    _metrics_server_thread = threading.Thread(target=run_server, daemon=True)
    _metrics_server_thread.start()


# Fonctions utilitaires
def record_llm_request(model: str, duration: float, status: str = "success"):
    llm_requests_total.labels(model=model, status=status).inc()
    if status == "success":
        llm_request_duration_seconds.labels(model=model).observe(duration)


def record_tool_execution(agent: str, tool: str, duration: float, error: bool = False):
    tool_execution_duration.labels(agent=agent, tool=tool).observe(duration)
    if error:
        tool_execution_errors.labels(agent=agent, tool=tool).inc()


def record_cache_hit(cache_type: str):
    cache_hits.labels(cache_type=cache_type).inc()


def record_cache_miss(cache_type: str):
    cache_misses.labels(cache_type=cache_type).inc()


def record_plan_cache_hit():
    plan_cache_hits.labels(cache_type="vector").inc()


def record_plan_cache_miss():
    plan_cache_misses.labels(cache_type="vector").inc()


def record_task_completed(task_name: str):
    tasks_completed_total.labels(task_name=task_name).inc()


def record_task_failed(task_name: str):
    tasks_failed_total.labels(task_name=task_name).inc()


def record_task_cancelled(task_name: str):
    tasks_cancelled_total.labels(task_name=task_name).inc()


def set_active_tasks(count: int):
    active_tasks.set(count)


def set_task_queue_size(size: int):
    task_queue_size.set(size)


def set_working_memory_size(size: int):
    working_memory_size.set(size)


def record_strategist_suggestion(category: str = "other"):
    strategist_suggestions_total.labels(category=category).inc()


def record_cortex_step(step: str, duration: float):
    cortex_step_duration.labels(step=step).observe(duration)