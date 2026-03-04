"""
Agent spécialisé dans l'extraction d'éléments d'interface utilisateur (boutons, menus, champs, etc.)
Utilise l'API d'accessibilité macOS pour obtenir des informations structurées sur les éléments UI.
"""

import time
from ...agents.base_agent import BaseAgent, Tool
from ...utils.logger import logger

try:
    import AppKit
    import ApplicationServices
    FOUND_APPKIT = True
except ImportError:
    FOUND_APPKIT = False
    logger.warning("AppKit non disponible, le UIElementAgent ne fonctionnera pas.")

class UIElementAgent(BaseAgent):
    """
    Agent capable d'extraire des informations sur les éléments d'interface utilisateur
    (boutons, champs de texte, menus, etc.) à l'écran.
    """

    def __init__(self, llm_service, bus, config):
        super().__init__("UIElementAgent", llm_service, bus)
        self.accessibility_available = self._check_accessibility()
        self.max_elements = config.get("max_elements", 20)  # Limite pour éviter de surcharger

    def _check_accessibility(self):
        if not FOUND_APPKIT:
            return False
        trusted = ApplicationServices.AXIsProcessTrusted()
        if not trusted:
            logger.warning("⚠️ Accessibilité non autorisée. L'agent UI ne fonctionnera pas.")
            return False
        return True

    def get_tools(self) -> list:
        return [
            Tool(
                name="get_ui_elements",
                description="Récupère la liste des éléments d'interface principaux de l'application active (boutons, champs, etc.)",
                parameters={
                    "type": "object",
                    "properties": {
                        "filter_by_role": {
                            "type": "string",
                            "description": "Filtre optionnel par rôle (ex: 'button', 'text field', 'menu')"
                        }
                    }
                }
            ),
            Tool(
                name="get_element_under_mouse",
                description="Récupère les informations détaillées de l'élément sous la souris",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            Tool(
                name="click_element",
                description="Tente de cliquer sur un élément identifié par son nom ou sa position",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Nom/titre de l'élément à cliquer"},
                        "role": {"type": "string", "description": "Rôle de l'élément (optionnel)"}
                    },
                    "required": ["name"]
                }
            )
        ]

    def _tool_get_ui_elements(self, filter_by_role: str = None) -> str:
        return self._get_ui_elements(filter_by_role)

    def _tool_get_element_under_mouse(self) -> str:
        return self._get_element_under_mouse()

    def _tool_click_element(self, name: str, role: str = None) -> str:
        return self._click_element(name, role)

    def _get_ui_elements(self, filter_by_role=None):
        if not self.accessibility_available:
            return "Accessibilité non disponible."

        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            active_app = workspace.frontmostApplication()
            if not active_app:
                return "Aucune application active."
            pid = active_app.processIdentifier()
            app_ref = ApplicationServices.AXUIElementCreateApplication(pid)
            if not app_ref:
                return "Impossible d'obtenir l'application."

            # Récupérer la fenêtre principale ou toutes les fenêtres
            err, focused_window = ApplicationServices.AXUIElementCopyAttributeValue(
                app_ref,
                ApplicationServices.kAXFocusedWindowAttribute,
                None
            )
            if err != 0 or not focused_window:
                # Pas de fenêtre focalisée, on prend la première fenêtre
                err, windows = ApplicationServices.AXUIElementCopyAttributeValue(
                    app_ref,
                    "AXWindows",
                    None
                )
                if err != 0 or not windows:
                    return "Aucune fenêtre trouvée."
                focused_window = windows[0]

            # Parcourir l'arbre pour trouver les éléments interactifs
            elements = self._extract_ui_elements(focused_window, depth=0, max_depth=5)
            if filter_by_role:
                elements = [e for e in elements if e.get("role", "").lower() == filter_by_role.lower()]

            if not elements:
                return "Aucun élément trouvé."

            # Limiter le nombre pour éviter les réponses trop longues
            elements = elements[:self.max_elements]
            result = "Éléments d'interface :\n"
            for e in elements:
                name = e.get("name", "sans nom")
                role = e.get("role", "inconnu")
                value = e.get("value", "")
                pos = e.get("position", "")
                result += f"- {name} ({role}) valeur='{value}' position={pos}\n"
            return result
        except Exception as e:
            logger.error(f"Erreur dans _get_ui_elements: {e}")
            return f"Erreur lors de la récupération des éléments UI : {str(e)}"

    def _extract_ui_elements(self, element, depth, max_depth):
        """Parcourt récursivement l'arbre d'accessibilité et extrait les éléments interactifs."""
        if depth > max_depth:
            return []

        elements = []
        try:
            # Rôle de l'élément
            err_role, role = ApplicationServices.AXUIElementCopyAttributeValue(
                element,
                ApplicationServices.kAXRoleAttribute,
                None
            )
            if err_role != 0 or not role:
                role = "unknown"

            # Titre/description
            err_title, title = ApplicationServices.AXUIElementCopyAttributeValue(
                element,
                ApplicationServices.kAXTitleAttribute,
                None
            )
            if err_title != 0 or not title:
                title = ""

            # Valeur (pour les champs de texte)
            err_value, value = ApplicationServices.AXUIElementCopyAttributeValue(
                element,
                ApplicationServices.kAXValueAttribute,
                None
            )
            if err_value != 0 or not value:
                value = ""

            # Position (pour cliquer)
            err_pos, position = ApplicationServices.AXUIElementCopyAttributeValue(
                element,
                ApplicationServices.kAXPositionAttribute,
                None
            )
            if err_pos == 0 and position:
                # Convertir le point en chaîne lisible
                try:
                    pos_str = f"({position.x}, {position.y})"
                except:
                    pos_str = str(position)
            else:
                pos_str = ""

            # Si c'est un élément interactif (bouton, champ, menu, etc.) ou s'il a un titre, on le garde
            interactive_roles = ["AXButton", "AXTextField", "AXCheckBox", "AXRadioButton",
                                 "AXMenu", "AXMenuItem", "AXComboBox", "AXSlider", "AXTab"]
            if role in interactive_roles or title:
                elements.append({
                    "name": title,
                    "role": role.replace("AX", "").lower(),
                    "value": value,
                    "position": pos_str
                })

            # Enfants
            err_children, children = ApplicationServices.AXUIElementCopyAttributeValue(
                element,
                ApplicationServices.kAXChildrenAttribute,
                None
            )
            if err_children == 0 and children:
                for child in children:
                    elements.extend(self._extract_ui_elements(child, depth+1, max_depth))
        except Exception as e:
            logger.debug(f"Erreur extraction élément: {e}")
        return elements

    def _get_element_under_mouse(self):
        if not self.accessibility_available:
            return "Accessibilité non disponible."

        try:
            # Obtenir la position de la souris
            mouse_loc = AppKit.NSEvent.mouseLocation()
            x, y = mouse_loc.x, mouse_loc.y

            # Obtenir l'application sous la souris
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            active_app = workspace.frontmostApplication()
            if not active_app:
                return "Aucune application active."
            pid = active_app.processIdentifier()
            app_ref = ApplicationServices.AXUIElementCreateApplication(pid)
            if not app_ref:
                return "Impossible d'obtenir l'application."

            # Trouver l'élément à cette position (nécessite un appel système plus complexe)
            # Pour simplifier, on utilise AXUIElementCopyElementAtPosition
            err, element = ApplicationServices.AXUIElementCopyElementAtPosition(app_ref, x, y)
            if err != 0 or not element:
                return "Aucun élément sous la souris."

            # Récupérer les infos de cet élément
            err_role, role = ApplicationServices.AXUIElementCopyAttributeValue(
                element,
                ApplicationServices.kAXRoleAttribute,
                None
            )
            err_title, title = ApplicationServices.AXUIElementCopyAttributeValue(
                element,
                ApplicationServices.kAXTitleAttribute,
                None
            )
            err_value, value = ApplicationServices.AXUIElementCopyAttributeValue(
                element,
                ApplicationServices.kAXValueAttribute,
                None
            )
            return f"Élément sous la souris : rôle={role}, titre={title}, valeur={value}"
        except Exception as e:
            logger.error(f"Erreur _get_element_under_mouse: {e}")
            return f"Erreur : {str(e)}"

    def _click_element(self, name, role=None):
        """Tente de cliquer sur un élément identifié par son nom."""
        # Pour l'instant, simple recherche et tentative de clic via AppleScript (à implémenter)
        return f"Clic sur '{name}' (non implémenté complètement)."

    def can_handle(self, query: str) -> bool:
        keywords = ["bouton", "menu", "interface", "cliquer", "souris", "élément", "ui"]
        return any(kw in query.lower() for kw in keywords)

    def handle(self, query: str) -> str:
        return self._tool_get_ui_elements()