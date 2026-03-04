#!/usr/bin/env python3
# main_gui.py - Lancement de l'interface graphique stable

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import Config
from app.core.engine import LucidEngine
from app.ui.window_stable import LucidWindowStable
from PyQt5.QtWidgets import QApplication

def main():
    print("🚀 Démarrage de l'interface graphique stable")
    time.sleep(0.1)

    cfg = Config.load("config.yaml")
    cfg.validate()

    engine = LucidEngine(cfg)
    app = QApplication(sys.argv)
    window = LucidWindowStable(engine)
    window.show()

    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        engine.stop()

if __name__ == "__main__":
    main()