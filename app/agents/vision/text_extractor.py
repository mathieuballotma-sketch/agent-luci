"""
Agent d'extraction de texte de l'écran via accessibilité macOS ou OCR.
Utilise la validation Pydantic pour les outils.
"""

import time
import threading
import subprocess
import tempfile
from PIL import Image
import pytesseract
from pydantic import BaseModel, Field
from ...agents.base_agent import BaseAgent, Tool
from ...utils.logger import logger
from ...utils.metrics import record_tool_execution

try:
    import AppKit
    import ApplicationServices
    FOUND_APPKIT = True
except ImportError:
    FOUND_APPKIT = False
    logger.warning("AppKit non disponible, le TextExtractorAgent ne fonctionnera pas.")


class TextExtractorAgentGetScreenTextContract(BaseModel):
    pass

class TextExtractorAgentGetTextAtPositionContract(BaseModel):
    x: int = Field(None, description="Coordonnée X")
    y: int = Field(None, description="Coordonnée Y")

class TextExtractorAgentGetUiElementInfoContract(BaseModel):
    pass


class TextExtractorAgent(BaseAgent):
    """
    Agent capable d'extraire le texte de l'écran ou de l'application active.
    """

    def __init__(self, llm_service, bus, config):
        super().__init__("TextExtractorAgent", llm_service, bus)
        self.accessibility_available = self._check_accessibility()
        self.use_ocr_fallback = config.get("use_ocr_fallback", True)
        self.min_text_length = config.get("min_text_length", 50)
        self.last_text = ""
        self.last_capture_time = 0
        self.cache_duration = config.get("cache_duration", 5)

    def _check_accessibility(self):
        if not FOUND_APPKIT:
            return False
        trusted = ApplicationServices.AXIsProcessTrusted()
        if not trusted:
            logger.warning("⚠️ Accessibilité non autorisée. L'agent utilisera l'OCR si configuré.")
            return False
        return True

    def get_tools(self) -> list:
        return [
            Tool(
                name="get_screen_text",
                description="Récupère tout le texte visible à l'écran (ou de l'application active).",
                contract=TextExtractorAgentGetScreenTextContract,
            ),
            Tool(
                name="get_text_at_position",
                description="Récupère le texte à une position donnée (x, y) ou sous la souris.",
                contract=TextExtractorAgentGetTextAtPositionContract,
            ),
            Tool(
                name="get_ui_element_info",
                description="Récupère des informations sur l'élément d'interface sous la souris.",
                contract=TextExtractorAgentGetUiElementInfoContract,
            )
        ]

    async def _tool_get_screen_text(self, **kwargs) -> str:
        import time
        start = time.time()
        try:
            result = self._capture_text()
            duration = time.time() - start
            record_tool_execution(self.name, "get_screen_text", duration, error=False)
            return result
        except Exception as e:
            duration = time.time() - start
            record_tool_execution(self.name, "get_screen_text", duration, error=True)
            raise

    async def _tool_get_text_at_position(self, x: int = None, y: int = None) -> str:
        return "Fonction non encore implémentée."

    async def _tool_get_ui_element_info(self, **kwargs) -> str:
        return "Fonction non encore implémentée."

    def _capture_text(self) -> str:
        now = time.time()
        if now - self.last_capture_time < self.cache_duration and self.last_text:
            logger.debug("Texte récupéré depuis le cache")
            return self.last_text

        text = None
        if self.accessibility_available:
            text = self._get_text_via_accessibility()
        if not text and self.use_ocr_fallback:
            text = self._ocr_screen()

        if text and len(text) >= self.min_text_length:
            self.last_text = text
            self.last_capture_time = now
            return text
        elif text:
            return text
        else:
            return "Aucun texte détecté à l'écran."

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

            err, focused_window = ApplicationServices.AXUIElementCopyAttributeValue(
                app_ref, ApplicationServices.kAXFocusedWindowAttribute, None
            )
            if err == 0 and focused_window:
                text = self._extract_all_text(focused_window, depth=0, max_depth=10)
                if text:
                    return text

            err, windows = ApplicationServices.AXUIElementCopyAttributeValue(app_ref, "AXWindows", None)
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
        if depth > max_depth:
            return ""
        parts = []
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
                break
        err, children = ApplicationServices.AXUIElementCopyAttributeValue(
            element, ApplicationServices.kAXChildrenAttribute, None
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

    def can_handle(self, query: str) -> bool:
        keywords = ["écran", "visible", "affiche", "vois", "texte", "image", "bouton"]
        return any(kw in query.lower() for kw in keywords)

    async def handle(self, query: str) -> str:
        return await self._tool_get_screen_text()