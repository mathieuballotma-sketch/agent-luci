"""
Gestionnaire d'élasticité matérielle.
Surveille les ressources système et ajuste dynamiquement la consommation.
Utilise une moyenne glissante pour lisser les pics de charge.
"""

import psutil
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Dict, Any, List
from ..utils.logger import logger
from ..utils.metrics import (
    system_load_cpu, system_load_memory,
    system_load_battery, system_thermal_pressure
)


@dataclass
class SystemLoad:
    cpu_percent: float
    memory_percent: float
    battery_percent: float | None
    on_battery: bool
    thermal_pressure: int  # 0-3 (0=normal, 3=critique)


class ElasticityEngine:
    """
    Moteur d'élasticité : surveille la charge et recommande des modèles.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._stop_event = threading.Event()
        self._thread = None
        self._listeners: List[Callable[[SystemLoad], None]] = []
        self.current_load = SystemLoad(0, 0, None, False, 0)

        # Mapping des profils vers les noms de modèles réels (à surcharger par le cortex)
        self.model_mapping = {
            "speed": config.get("speed_model", "qwen2.5:3b"),
            "balanced": config.get("balanced_model", "qwen2.5:7b"),
            "quality": config.get("quality_model", "qwen2.5:14b")
        }

        # Pour la moyenne glissante de la charge CPU (5 échantillons)
        self.cpu_history = deque(maxlen=5)
        self.thermal_history = deque(maxlen=3)

        # Intervalle de surveillance (secondes)
        self.monitor_interval = config.get("elasticity_interval", 2)

    def start(self):
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("📊 ElasticityEngine démarré")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def add_listener(self, callback: Callable[[SystemLoad], None]):
        self._listeners.append(callback)

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            load = self._get_system_load()
            self.current_load = load

            # Mise à jour des métriques Prometheus
            system_load_cpu.set(load.cpu_percent)
            system_load_memory.set(load.memory_percent)
            if load.battery_percent is not None:
                system_load_battery.set(load.battery_percent)
            system_thermal_pressure.set(load.thermal_pressure)

            for cb in self._listeners:
                try:
                    cb(load)
                except Exception as e:
                    logger.error(f"Erreur dans listener elasticity: {e}")
            time.sleep(self.monitor_interval)

    def _get_system_load(self) -> SystemLoad:
        # Charge CPU avec moyenne glissante
        raw_cpu = psutil.cpu_percent(interval=0.5)
        self.cpu_history.append(raw_cpu)
        smoothed_cpu = sum(self.cpu_history) / len(self.cpu_history)

        mem = psutil.virtual_memory().percent

        battery = None
        on_battery = False
        if hasattr(psutil, "sensors_battery"):
            batt = psutil.sensors_battery()
            if batt:
                battery = batt.percent
                on_battery = not batt.power_plugged

        thermal = self._get_thermal_pressure(smoothed_cpu)
        self.thermal_history.append(thermal)
        smoothed_thermal = int(sum(self.thermal_history) / len(self.thermal_history))

        return SystemLoad(smoothed_cpu, mem, battery, on_battery, smoothed_thermal)

    def _get_thermal_pressure(self, smoothed_cpu: float) -> int:
        """
        Estime la pression thermique sur macOS.
        Retourne 0 (normal) à 3 (critique).
        Utilise une moyenne glissante sur la température CPU si disponible,
        sinon se base sur la charge CPU lissée.
        """
        # Essayer de lire la température CPU via psutil (si disponible)
        if hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                # Chercher la température CPU sur différents capteurs macOS
                cpu_temp = None
                for key in ['cpu_thermal', 'TC0P', 'Tp0', 'Tp01', 'Tp05', 'Tp0H', 'Tp0P']:
                    if key in temps and temps[key]:
                        cpu_temp = temps[key][0].current
                        break

                if cpu_temp is not None:
                    if cpu_temp > 95:
                        return 3
                    elif cpu_temp > 85:
                        return 2
                    elif cpu_temp > 70:
                        return 1
                    else:
                        return 0
            except Exception as e:
                logger.debug(f"Impossible de lire la température CPU: {e}")

        # Fallback sur la charge CPU lissée
        if smoothed_cpu > 90:
            return 3
        elif smoothed_cpu > 75:
            return 2
        elif smoothed_cpu > 50:
            return 1
        else:
            return 0

    def get_recommended_profile(self) -> str:
        """Retourne le profil recommandé : 'speed', 'balanced' ou 'quality'."""
        load = self.current_load
        if load.thermal_pressure >= 2 or (load.on_battery and load.battery_percent and load.battery_percent < 20):
            return "speed"
        elif load.cpu_percent > 60 or load.memory_percent > 80:
            return "balanced"
        else:
            return "quality"

    def get_recommended_model(self) -> str:
        """Retourne le nom réel du modèle recommandé."""
        profile = self.get_recommended_profile()
        return self.model_mapping.get(profile, "qwen2.5:7b")

    def get_max_workers(self) -> int:
        """Ajuste le nombre de workers selon la charge."""
        base = self.config.get("base_workers", 3)
        load = self.current_load
        if load.thermal_pressure >= 2 or load.cpu_percent > 90:
            return 1
        elif load.cpu_percent > 70:
            return max(1, base - 1)
        else:
            return base