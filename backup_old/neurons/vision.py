# app/brain/neurons/vision.py
import objc
import AppKit
import ApplicationServices
import threading
import time
import subprocess
import tempfile
from PIL import Image
import pytesseract
from ...utils.logger import logger

class OpticalNerve:
    """
    Neurone visuel utilisant l'API d'accessibilité macOS.
    Récupère le texte de l'application active avec une recherche approfondie.
    """

    def __init__(self, config):
        self.bus = None
        self.last_text = ""
        self.running = False
        self._observer = None
        self._poll_interval = getattr(config, 'poll_interval', 2.0)  # secondes
        self.use_ocr_fallback = getattr(config, 'use_ocr_fallback', True)
        self.min_text_length = getattr(config, 'min_text_length', 50)  # caractères minimum pour considérer le texte
        self._check_accessibility()

    def _check_accessibility(self):
        trusted = ApplicationServices.AXIsProcessTrusted()
        if not trusted:
            logger.warning(
                "⚠️ Accessibilité non autorisée. "
                "Va dans Préférences Système → Confidentialité → Accessibilité "
                "et ajoute ton app (ou le terminal). L'OCR sera utilisé en attendant."
            )
            self.accessibility_available = False
        else:
            logger.info("✅ Droits d'accessibilité accordés, utilisation prioritaire.")
            self.accessibility_available = True

    def start(self, bus):
        self.bus = bus
        self.running = True

        # Observer les changements d'application active
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserver_selector_name_object_(
            self._make_observer(),
            'appDidChange:',
            AppKit.NSWorkspaceDidActivateApplicationNotification,
            None
        )

        # Thread de lecture périodique
        threading.Thread(target=self._poll_loop, daemon=True).start()
        logger.info(f"👁️ Vision démarrée (intervalle {self._poll_interval}s, accessibilité={self.accessibility_available})")

    def _make_observer(self):
        class _Obs(AppKit.NSObject):
            def appDidChange_(self, notif):
                self._on_app_change()
        self._observer = _Obs.alloc().init()
        # On utilise une closure pour capturer self
        import weakref
        self_ref = weakref.ref(self)
        def on_change():
            s = self_ref()
            if s:
                s._on_app_change()
        self._observer._on_app_change = on_change
        return self._observer

    def _on_app_change(self):
        self._read_focused_text()

    def _poll_loop(self):
        while self.running:
            time.sleep(self._poll_interval)
            self._read_focused_text()

    def _read_focused_text(self):
        try:
            if self.accessibility_available:
                text = self._get_text_via_accessibility()
                if text:
                    self._process_text(text)
                    return
            if self.use_ocr_fallback:
                text = self._ocr_screen()
                if text:
                    self._process_text(text)
        except Exception as e:
            logger.debug(f"Erreur lecture: {e}")

    def _get_text_via_accessibility(self):
        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            active_app = workspace.frontmostApplication()
            if not active_app:
                return None
            pid = active_app.processIdentifier()
            app_ref = ApplicationServices.AXUIElementCreateApplication(pid)
            if not app_ref:
                return None

            # Essayer d'obtenir la fenêtre focalisée
            err, focused_window = ApplicationServices.AXUIElementCopyAttributeValue(
                app_ref,
                ApplicationServices.kAXFocusedWindowAttribute,
                None
            )
            if err == 0 and focused_window:
                text = self._extract_all_text(focused_window, depth=0, max_depth=10)
                if text:
                    return text

            # Sinon, parcourir toutes les fenêtres de l'application
            err, windows = ApplicationServices.AXUIElementCopyAttributeValue(
                app_ref,
                "AXWindows",  # pas de constante mais chaîne
                None
            )
            if err == 0 and windows:
                all_text = []
                for win in windows:
                    text = self._extract_all_text(win, depth=0, max_depth=10)
                    if text:
                        all_text.append(text)
                return "\n".join(all_text) if all_text else None

            return None
        except Exception as e:
            logger.debug(f"Erreur accessibilité: {e}")
            return None

    def _extract_all_text(self, element, depth, max_depth):
        """Parcourt récursivement l'arbre AX et collecte tout le texte des attributs pertinents."""
        if depth > max_depth:
            return ""

        parts = []
        # Attributs textuels courants
        text_attrs = [
            ApplicationServices.kAXValueAttribute,
            ApplicationServices.kAXTitleAttribute,
            ApplicationServices.kAXDescriptionAttribute,
            ApplicationServices.kAXHelpAttribute,
            ApplicationServices.kAXSelectedTextAttribute,
        ]
        for attr in text_attrs:
            err, val = ApplicationServices.AXUIElementCopyAttributeValue(element, attr, None)
            if err == 0 and isinstance(val, str) and val.strip():
                parts.append(val.strip())
                break  # on prend le premier trouvé pour cet élément

        # Vérifier le rôle pour ignorer certains éléments (boutons, etc.)? Optionnel.

        # Enfants
        err, children = ApplicationServices.AXUIElementCopyAttributeValue(
            element,
            ApplicationServices.kAXChildrenAttribute,
            None
        )
        if err == 0 and children:
            for child in children:
                child_text = self._extract_all_text(child, depth+1, max_depth)
                if child_text:
                    parts.append(child_text)

        return "\n".join(parts).strip()

    def _ocr_screen(self):
        try:
            with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
                subprocess.run(['screencapture', '-x', tmp.name], check=True)
                img = Image.open(tmp.name)
                text = pytesseract.image_to_string(img, lang='fra+eng').strip()
                return text or None
        except Exception as e:
            logger.debug(f"Erreur OCR: {e}")
            return None

    def _process_text(self, new_text):
        if not new_text:
            return
        # Filtrer les textes trop courts (simples titres)
        if len(new_text) < self.min_text_length:
            logger.debug(f"Texte trop court ({len(new_text)} chars), ignoré")
            return
        if self._significant_change(new_text):
            logger.debug(f"📝 Nouveau texte ({len(new_text)} caractères)")
            self.last_text = new_text
            if self.bus:
                self.bus.update(new_text)
        else:
            logger.debug("Aucun changement significatif")

    def _significant_change(self, new_text):
        if not self.last_text:
            return True
        if abs(len(new_text) - len(self.last_text)) > 500:
            return True
        old_words = set(self.last_text.split())
        new_words = set(new_text.split())
        common = old_words.intersection(new_words)
        if len(common) < max(len(old_words), len(new_words)) * 0.3:
            return True
        return False

    def stop(self):
        self.running = False
        if self._observer:
            nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
            nc.removeObserver_(self._observer)
        logger.info("👁️ Vision arrêtée")