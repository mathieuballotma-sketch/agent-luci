"""
Agent spécialisé dans la description d'images à l'écran.
Utilise un modèle de vision-langage léger (moondream) si disponible.
"""

import base64
import subprocess
import tempfile
from ...agents.base_agent import BaseAgent, Tool
from ...utils.logger import logger

try:
    import moondream as md
    MOONDREAM_AVAILABLE = True
except ImportError:
    MOONDREAM_AVAILABLE = False
    logger.warning("Module 'moondream' non disponible. L'agent ImageDescriber utilisera un fallback simple.")

class ImageDescriberAgent(BaseAgent):
    """
    Agent capable de décrire le contenu des images affichées à l'écran.
    Utilise un VLM (Vision-Language Model) pour générer des descriptions textuelles.
    """

    def __init__(self, llm_service, bus, config):
        super().__init__("ImageDescriberAgent", llm_service, bus)
        self.model = None
        if MOONDREAM_AVAILABLE:
            try:
                # Charger le modèle (à ajuster selon la bibliothèque)
                # self.model = md.vl(model='moondream2')
                logger.info("Modèle Moondream chargé (simulé pour l'instant)")
            except Exception as e:
                logger.error(f"Erreur chargement Moondream: {e}")
        self.use_fallback = config.get("use_fallback", True)

    def get_tools(self) -> list:
        return [
            Tool(
                name="describe_screen",
                description="Décrit le contenu visuel général de l'écran (ce qu'on voit).",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            Tool(
                name="describe_image_at_position",
                description="Décrit l'image à une position donnée (x, y) ou sous la souris.",
                parameters={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "Coordonnée X (optionnel)"},
                        "y": {"type": "integer", "description": "Coordonnée Y (optionnel)"}
                    }
                }
            )
        ]

    def _tool_describe_screen(self) -> str:
        return self._describe_screen()

    def _tool_describe_image_at_position(self, x: int = None, y: int = None) -> str:
        return self._describe_image_at_position(x, y)

    def _capture_screen(self) -> str:
        """Capture l'écran et retourne le chemin du fichier temporaire."""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(['screencapture', '-x', tmp_path], check=True, capture_output=True)
            return tmp_path
        except Exception as e:
            logger.error(f"Erreur capture écran: {e}")
            return None

    def _describe_screen(self):
        img_path = self._capture_screen()
        if not img_path:
            return "Impossible de capturer l'écran."

        if MOONDREAM_AVAILABLE and self.model:
            # Utiliser Moondream pour décrire
            try:
                # with open(img_path, "rb") as f:
                #     image = md.Image(f.read())
                # description = self.model.caption(image)["caption"]
                description = "Description simulée : L'écran affiche plusieurs fenêtres, du texte et des icônes."
                return description
            except Exception as e:
                logger.error(f"Erreur Moondream: {e}")
                if not self.use_fallback:
                    return f"Erreur de description: {e}"

        # Fallback simple
        return "L'écran contient du texte et des éléments graphiques (description limitée par manque de modèle VLM)."

    def _describe_image_at_position(self, x=None, y=None):
        # Pour l'instant, on ne capture qu'une région, mais c'est plus complexe.
        return "Fonction non implémentée."

    def can_handle(self, query: str) -> bool:
        keywords = ["image", "photo", "voir", "affiche", "dessin", "graphique"]
        return any(kw in query.lower() for kw in keywords)

    def handle(self, query: str) -> str:
        return self._tool_describe_screen()