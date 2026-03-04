# app/bridges/macos.py
import time
from PyQt5.QtCore import QTimer

def apply_max_level_and_behavior(window):
    """Applique le niveau maximum et le comportement de collection. Retourne True si réussi."""
    try:
        import AppKit
        import objc
        MAX_LEVEL = 2147483647
        wid = int(window.winId())
        native_window = None
        for w in AppKit.NSApp().windows():
            if w.windowNumber() == wid:
                native_window = w
                break
        if native_window:
            # Niveau maximum
            native_window.setLevel_(MAX_LEVEL)
            native_window.setOpaque_(False)
            native_window.setBackgroundColor_(AppKit.NSColor.clearColor())
            # Comportement pour être sur tous les espaces et au-dessus
            behavior = (
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |   # rejoindre tous les espaces
                AppKit.NSWindowCollectionBehaviorStationary |          # ne bouge pas avec l'espace
                AppKit.NSWindowCollectionBehaviorIgnoresCycle |       # ignore le cycle de fenêtres
                2048                                                   # NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            native_window.setCollectionBehavior_(behavior)
            print("✅ Niveau max et comportement appliqués.")
            return True
        else:
            print("⚠️ Fenêtre native non trouvée.")
            return False
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False

def start_level_watchdog(window, interval=1000):
    """
    Watchdog qui tente d'appliquer niveau et comportement à chaque cycle,
    jusqu'à succès, puis continue de vérifier.
    """
    success = False
    def check_and_restore():
        nonlocal success
        try:
            if apply_max_level_and_behavior(window):
                success = True
        except Exception as e:
            print(f"⚠️ Erreur watchdog: {e}")

    timer = QTimer()
    timer.timeout.connect(check_and_restore)
    timer.start(interval)
    print(f"🐶 Watchdog démarré (intervalle {interval}ms)")
    return timer
