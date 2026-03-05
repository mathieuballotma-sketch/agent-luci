# app/agents/computer_control_agent.py
"""
Agent de contrôle de l'ordinateur — version étendue.
Ajoute des outils pour Mail, Safari et l'organisation des fenêtres.
Version avec arrangement de fenêtres amélioré (création de fenêtre pour Mail).
Optimisé pour la rapidité : timeouts réduits, polling plus fréquent.
"""

import asyncio
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Optional, List, Tuple

import pyautogui
from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger
from app.utils.metrics import record_tool_execution

try:
    import AppKit
    FOUND_APPKIT = True
    from AppKit import NSScreen
except ImportError:
    FOUND_APPKIT = False
    logger.warning("AppKit non disponible — détection d'app active désactivée, arrangement de fenêtres limité.")


# ---------------------------------------------------------------------------
# Constantes centralisées
# ---------------------------------------------------------------------------
OPEN_KEYWORDS      = ["ouvre", "lance", "open", "launch"]
TYPE_KEYWORDS      = ["tape", "écris", "type"]
CLICK_KEYWORDS     = ["clique", "click"]
SCREENSHOT_KEYWORDS = ["screenshot", "capture écran"]
MOVE_KEYWORDS      = ["déplace", "move"]
ARRANGE_KEYWORDS   = ["côte à côte", "side by side", "organise", "grille", "disposition"]
MAIL_KEYWORDS      = ["mail", "email", "courriel", "message"]
SAFARI_KEYWORDS    = ["safari", "navigateur", "internet", "page web", "url"]

NOTES_APPS         = ["notes"]
KNOWN_APPS         = ["notes", "calculatrice", "safari", "mail", "calendar",
                      "terminal", "finder", "chrome", "firefox", "slack"]

OPEN_PATTERNS = [
    r"ouvre (?:l'application\s+)?([a-zA-Z0-9\s]+)",
    r"lance (?:l'application\s+)?([a-zA-Z0-9\s]+)",
    r"open (?:the )?([a-zA-Z0-9\s]+)",
    r"launch (?:the )?([a-zA-Z0-9\s]+)",
]
TYPE_PATTERNS = [
    r"tape (.*)",
    r"écris (.*)",
    r"type (.*)",
]
QUOTE_PATTERN   = r"['\"](.+?)['\"]"
COORDS_PATTERN  = r"(\d+)\s*[,\s]\s*(\d+)"
ARTICLE_PATTERN = r"^(l'|le |la |les )"

SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "screenshots"
)

# Patterns pour l'organisation des fenêtres
ARRANGE_PATTERNS = {
    "side_by_side": r"(c[ôo]te[ -]à[ -]c[ôo]te|side[ -]by[ -]side)",
    "grid_2x2": r"(grille|2x2|quatre|four)",
}


# ---------------------------------------------------------------------------
# Contrats Pydantic
# ---------------------------------------------------------------------------
class ComputerControlOpenApplicationContract(BaseModel):
    app_name: str = Field(..., description="Nom exact de l'application")

class ComputerControlTypeTextContract(BaseModel):
    text: str          = Field(..., description="Texte à taper")
    interval: float    = Field(0.05, description="Intervalle entre frappes (s)")
    app_name: Optional[str] = Field(None, description="Application cible")
    correct_spelling: bool  = Field(False, description="Corriger orthographe")

class ComputerControlPressKeyContract(BaseModel):
    key: str = Field(..., description="Touche à presser")

class ComputerControlClickContract(BaseModel):
    x: int         = Field(..., description="Coordonnée X")
    y: int         = Field(..., description="Coordonnée Y")
    button: str    = Field("left", description="Bouton (left/right/middle)")
    duration: float = Field(0.5, description="Durée déplacement (s)")

class ComputerControlMoveMouseContract(BaseModel):
    x: int         = Field(..., description="Coordonnée X")
    y: int         = Field(..., description="Coordonnée Y")
    duration: float = Field(0.5, description="Durée déplacement (s)")

class ComputerControlGetScreenshotContract(BaseModel):
    pass

class ComputerControlMailComposeContract(BaseModel):
    to: str = Field(..., description="Destinataire (adresse email)")
    subject: str = Field("", description="Sujet du message")
    body: str = Field("", description="Corps du message")
    send: bool = Field(False, description="Envoyer immédiatement après rédaction")

class ComputerControlSafariOpenUrlContract(BaseModel):
    url: str = Field(..., description="URL à ouvrir")
    new_tab: bool = Field(False, description="Ouvrir dans un nouvel onglet")

class ComputerControlArrangeWindowsContract(BaseModel):
    layout: str = Field(..., description="Type de disposition: 'side_by_side', 'grid_2x2'")
    apps: Optional[List[str]] = Field(None, description="Liste des applications concernées (optionnel)")


# ---------------------------------------------------------------------------
# Agent principal
# ---------------------------------------------------------------------------
class ComputerControlAgent(BaseAgent):
    """
    Agent capable d'effectuer des actions sur l'ordinateur de façon visible.
    Version étendue avec outils pour Mail, Safari et organisation des fenêtres.
    """

    def __init__(self, llm_service, bus, config: dict):
        super().__init__("ComputerControlAgent", llm_service, bus)
        pyautogui.FAILSAFE = True

        self.visible_mode               = config.get("visible_actions", True)
        self.move_duration              = config.get("move_duration", 0.5)
        self.type_interval              = config.get("type_interval", 0.05)
        self.use_spell_check            = config.get("use_spell_check", False)
        self.use_applescript_for_typing = config.get("use_applescript_for_typing", False)
        self.use_paste_for_typing       = config.get("use_paste_for_typing", True)

        logger.info(f"🖱️ ComputerControlAgent initialisé (mode visible={self.visible_mode})")

    def get_tools(self) -> list:
        return [
            Tool(name="open_application",
                 description="Ouvre une application macOS.",
                 contract=ComputerControlOpenApplicationContract),
            Tool(name="type_text",
                 description="Tape un texte. Si l'app cible est Notes, crée une nouvelle note.",
                 contract=ComputerControlTypeTextContract),
            Tool(name="press_key",
                 description="Presse une touche spéciale (enter, tab, escape…).",
                 contract=ComputerControlPressKeyContract),
            Tool(name="click",
                 description="Clique à une position (x, y) à l'écran.",
                 contract=ComputerControlClickContract),
            Tool(name="move_mouse",
                 description="Déplace la souris à une position (x, y).",
                 contract=ComputerControlMoveMouseContract),
            Tool(name="get_screenshot",
                 description="Capture l'écran et retourne le chemin du fichier.",
                 contract=ComputerControlGetScreenshotContract),
            Tool(name="mail_compose",
                 description="Ouvre Mail et crée un nouveau message.",
                 contract=ComputerControlMailComposeContract),
            Tool(name="safari_open_url",
                 description="Ouvre une URL dans Safari.",
                 contract=ComputerControlSafariOpenUrlContract),
            Tool(name="arrange_windows",
                 description="Organise les fenêtres selon une disposition (côte à côte, grille).",
                 contract=ComputerControlArrangeWindowsContract),
        ]

    # -----------------------------------------------------------------------
    # Méthodes auxiliaires asynchrones
    # -----------------------------------------------------------------------
    async def _run_applescript(self, script: str, timeout: float = 5.0) -> tuple[bool, str]:
        """Exécute un AppleScript avec un timeout (5s par défaut)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode == 0:
                return True, stdout.decode().strip()
            return False, stderr.decode().strip()
        except asyncio.TimeoutError:
            logger.error(f"AppleScript timeout après {timeout}s")
            return False, "Timeout"
        except Exception as e:
            logger.error(f"Erreur AppleScript inattendue : {e}")
            return False, str(e)

    async def _activate_app(self, app_name: str):
        script = f'tell application "{app_name}" to activate'
        await self._run_applescript(script, timeout=3.0)

    def _get_active_app_name(self) -> Optional[str]:
        if not FOUND_APPKIT:
            return None
        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            active_app = workspace.frontmostApplication()
            return active_app.localizedName() if active_app else None
        except Exception as e:
            logger.debug(f"Erreur get_active_app_name : {e}")
            return None

    async def _wait_for_app_active(self, app_name: str, timeout: float = 2.0) -> bool:
        """Attend que l'application devienne active avec un polling rapide."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            active = self._get_active_app_name()
            if active and app_name.lower() in active.lower():
                return True
            await asyncio.sleep(0.1)
        logger.warning(f"'{app_name}' non détectée au premier plan après {timeout}s")
        return False

    async def _create_new_note_in_notes(self) -> bool:
        script = """
        tell application "Notes"
            activate
        end tell
        tell application "System Events"
            keystroke "n" using command down
        end tell
        """
        success, error = await self._run_applescript(script, timeout=3.0)
        if not success:
            logger.error(f"Création de note échouée : {error}")
        return success

    async def _type_text_with_applescript(self, text: str, interval: float = 0.05,
                                           use_paste: bool = False) -> bool:
        if use_paste:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pbcopy",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate(input=text.encode('utf-8'))
                await asyncio.sleep(0.1)
                script = 'tell application "System Events" to keystroke "v" using command down'
                success, error = await self._run_applescript(script, timeout=2.0)
                return success
            except Exception as e:
                logger.error(f"Erreur collage AppleScript: {e}")
                return False
        else:
            escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            script = f"""
            set textToType to "{escaped}"
            repeat with i from 1 to count of characters of textToType
                tell application "System Events" to keystroke (character i of textToType)
                delay {interval}
            end repeat
            """
            success, error = await self._run_applescript(script, timeout=5.0)
            if not success:
                logger.error(f"AppleScript typing échoué : {error}")
            return success

    # -----------------------------------------------------------------------
    # Implémentations des outils existants
    # -----------------------------------------------------------------------
    async def _tool_open_application(self, app_name: str) -> str:
        start = time.time()
        # Vérifier si l'application est déjà ouverte (timeout court)
        check_script = f'''
        tell application "System Events"
            return (exists process "{app_name}")
        end tell
        '''
        success, output = await self._run_applescript(check_script, timeout=3.0)
        if success and output.strip().lower() == "true":
            # Déjà ouverte → simple activation
            await self._activate_app(app_name)
            record_tool_execution(self.name, "open_application", time.time() - start, error=False)
            return f"✅ Application '{app_name}' déjà ouverte, activation."
        # Sinon, on l'ouvre normalement
        try:
            proc = await asyncio.create_subprocess_exec(
                "open", "-a", app_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Erreur inconnue"
                logger.error(f"Échec ouverture '{app_name}' : {error_msg}")
                record_tool_execution(self.name, "open_application", time.time() - start, error=True)
                return f"❌ Impossible d'ouvrir '{app_name}' : {error_msg}"
            # Attendre que l'application devienne active (timeout réduit)
            await self._wait_for_app_active(app_name, timeout=2.0)
            await self._activate_app(app_name)
            record_tool_execution(self.name, "open_application", time.time() - start, error=False)
            return f"✅ Application '{app_name}' ouverte."
        except Exception as e:
            logger.error(f"Exception open_application: {e}")
            record_tool_execution(self.name, "open_application", time.time() - start, error=True)
            return f"❌ Erreur ouverture '{app_name}': {e}"

    async def _tool_type_text(self, text: str, interval: float = 0.05,
                               app_name: Optional[str] = None,
                               correct_spelling: bool = False) -> str:
        start = time.time()
        logger.info(f"🚀 type_text : '{text[:40]}…' | app={app_name}")
        target_app = app_name
        if app_name:
            await self._activate_app(app_name)
            await self._wait_for_app_active(app_name, timeout=2.0)
        else:
            active = self._get_active_app_name()
            if active and any(n in active.lower() for n in NOTES_APPS):
                target_app = active
        if target_app and any(n in target_app.lower() for n in NOTES_APPS):
            logger.info("   → Notes détectée : création d'une nouvelle note")
            if not await self._create_new_note_in_notes():
                logger.warning("   → Fallback : Cmd+N via pyautogui")
                pyautogui.hotkey('command', 'n')
            await self._wait_for_app_active("Notes", timeout=2.0)
        if target_app and any(n in target_app.lower() for n in NOTES_APPS):
            logger.info("   → Utilisation d'AppleScript avec collage pour Notes")
            success = await self._type_text_with_applescript(text, interval, use_paste=True)
            if success:
                record_tool_execution(self.name, "type_text", time.time() - start, error=False)
                return f"✅ Texte tapé ({len(text)} car.) via AppleScript (collage)."
            else:
                logger.warning("   → Échec AppleScript, fallback sur méthode standard")
        if self.use_applescript_for_typing:
            success = await self._type_text_with_applescript(text, interval, use_paste=self.use_paste_for_typing)
            if success:
                method = "collage" if self.use_paste_for_typing else "frappe AppleScript"
                record_tool_execution(self.name, "type_text", time.time() - start, error=False)
                return f"✅ Texte tapé ({len(text)} car.) via {method}."
            else:
                logger.warning("   → Échec AppleScript, fallback pyautogui (dégradé)")
                pyautogui.typewrite(text, interval=interval)
                record_tool_execution(self.name, "type_text_degraded", time.time() - start, error=True)
                return f"⚠️ Texte tapé ({len(text)} car.) via fallback pyautogui."
        else:
            if self.use_paste_for_typing:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "pbcopy",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await proc.communicate(input=text.encode('utf-8'))
                    await asyncio.sleep(0.2)
                    pyautogui.hotkey('command', 'v')
                    record_tool_execution(self.name, "type_text", time.time() - start, error=False)
                    return f"✅ Texte tapé ({len(text)} car.) via collage."
                except Exception as e:
                    logger.error(f"Erreur collage: {e}")
                    pyautogui.typewrite(text, interval=interval)
                    record_tool_execution(self.name, "type_text_degraded", time.time() - start, error=True)
                    return f"⚠️ Texte tapé ({len(text)} car.) via fallback pyautogui."
            else:
                pyautogui.typewrite(text, interval=interval)
                record_tool_execution(self.name, "type_text", time.time() - start, error=False)
                return f"✅ Texte tapé ({len(text)} car.) via pyautogui."

    async def _tool_press_key(self, key: str) -> str:
        start = time.time()
        pyautogui.press(key)
        record_tool_execution(self.name, "press_key", time.time() - start, error=False)
        return f"✅ Touche '{key}' pressée."

    async def _tool_click(self, x: int, y: int, button: str = "left", duration: float = 0.5) -> str:
        start = time.time()
        if duration > 0:
            pyautogui.moveTo(x, y, duration=duration)
            await asyncio.sleep(0.1)
        pyautogui.click(button=button)
        record_tool_execution(self.name, "click", time.time() - start, error=False)
        return f"✅ Clic {button} à ({x}, {y})."

    async def _tool_move_mouse(self, x: int, y: int, duration: float = 0.5) -> str:
        start = time.time()
        pyautogui.moveTo(x, y, duration=duration)
        record_tool_execution(self.name, "move_mouse", time.time() - start, error=False)
        return f"✅ Souris déplacée à ({x}, {y})."

    async def _tool_get_screenshot(self) -> str:
        start = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        filepath = os.path.join(SCREENSHOT_DIR, filename)
        pyautogui.screenshot(filepath)
        record_tool_execution(self.name, "get_screenshot", time.time() - start, error=False)
        return f"✅ Capture d'écran : {filepath}"

    # -----------------------------------------------------------------------
    # Nouveaux outils
    # -----------------------------------------------------------------------
    async def _tool_mail_compose(self, to: str, subject: str = "", body: str = "", send: bool = False) -> str:
        start = time.time()
        try:
            to_esc = to.replace('"', '\\"')
            subject_esc = subject.replace('"', '\\"')
            body_esc = body.replace('"', '\\"').replace('\n', '\\n')
            script = f'''
            tell application "Mail"
                activate
                set newMessage to make new outgoing message with properties {{subject:"{subject_esc}", content:"{body_esc}"}}
                tell newMessage
                    make new to recipient at end of to recipients with properties {{address:"{to_esc}"}}
                end tell
                {"send newMessage" if send else ""}
            end tell
            '''
            success, error = await self._run_applescript(script, timeout=10.0)
            if success:
                action = "envoyé" if send else "préparé"
                record_tool_execution(self.name, "mail_compose", time.time() - start, error=False)
                return f"✅ Email {action} pour {to}."
            else:
                record_tool_execution(self.name, "mail_compose", time.time() - start, error=True)
                return f"❌ Erreur lors de la création de l'email: {error}"
        except Exception as e:
            logger.error(f"Exception mail_compose: {e}")
            record_tool_execution(self.name, "mail_compose", time.time() - start, error=True)
            return f"❌ Erreur: {e}"

    async def _tool_safari_open_url(self, url: str, new_tab: bool = False) -> str:
        start = time.time()
        try:
            await self._activate_app("Safari")
            await self._wait_for_app_active("Safari", timeout=2.0)
            if new_tab:
                script = f'''
                tell application "Safari"
                    tell window 1 to make new tab with properties {{URL:"{url}"}}
                end tell
                '''
            else:
                script = f'''
                tell application "Safari" to set URL of document 1 to "{url}"
                '''
            success, error = await self._run_applescript(script, timeout=5.0)
            if success:
                record_tool_execution(self.name, "safari_open_url", time.time() - start, error=False)
                return f"✅ URL ouverte dans Safari."
            else:
                record_tool_execution(self.name, "safari_open_url", time.time() - start, error=True)
                return f"❌ Erreur: {error}"
        except Exception as e:
            logger.error(f"Exception safari_open_url: {e}")
            record_tool_execution(self.name, "safari_open_url", time.time() - start, error=True)
            return f"❌ Erreur: {e}"

    async def _get_screen_size(self) -> Tuple[int, int]:
        """Retourne la largeur et hauteur de l'écran principal."""
        if FOUND_APPKIT:
            screen = NSScreen.mainScreen()
            frame = screen.frame()
            return int(frame.size.width), int(frame.size.height)
        else:
            # Fallback sur une taille courante (1440x900)
            return 1440, 900

    async def _arrange_side_by_side(self, apps: List[str]) -> str:
        """Place deux applications côte à côte, avec création de fenêtre pour Mail si nécessaire."""
        if len(apps) != 2:
            return "❌ Pour la disposition côte à côte, il faut exactement deux applications."
        
        width, height = await self._get_screen_size()
        half_width = width // 2
        errors = []
        
        for i, app in enumerate(apps):
            logger.info(f"Arrangement: traitement de {app}")
            
            # Activer l'application et attendre qu'elle soit active
            await self._activate_app(app)
            if not await self._wait_for_app_active(app, timeout=3.0):
                errors.append(f"{app} ne s'est pas activée")
                continue
            
            # Attendre un peu que l'application soit prête
            await asyncio.sleep(0.5)
            
            # Pour Mail, s'assurer qu'une fenêtre existe
            if app.lower() == "mail":
                # Vérifier si une fenêtre existe déjà
                check_script = '''
                tell application "Mail"
                    if exists window 1 then
                        return true
                    else
                        return false
                    end if
                end tell
                '''
                success, output = await self._run_applescript(check_script, timeout=3.0)
                if not success or "false" in output.lower():
                    logger.info("Aucune fenêtre Mail trouvée, création d'une nouvelle fenêtre")
                    new_window_script = '''
                    tell application "Mail"
                        activate
                        make new window
                    end tell
                    '''
                    await self._run_applescript(new_window_script, timeout=3.0)
                    await asyncio.sleep(1.0)
            
            # Positionner la fenêtre
            x = 0 if i == 0 else half_width
            script = f'''
            tell application "System Events"
                tell process "{app}"
                    set position of window 1 to {{{x}, 0}}
                    set size of window 1 to {{{half_width}, {height}}}
                end tell
            end tell
            '''
            logger.debug(f"Script pour {app} : {script}")
            success, err = await self._run_applescript(script, timeout=5.0)
            if not success:
                logger.error(f"Erreur arrangement pour {app}: {err}")
                errors.append(f"{app}: {err}")
            else:
                logger.info(f"Fenêtre de {app} positionnée avec succès")
        
        if errors:
            return f"⚠️ Disposition partielle : {', '.join(errors)}"
        return f"✅ Fenêtres de {apps[0]} et {apps[1]} disposées côte à côte."

    async def _arrange_grid_2x2(self, apps: List[str]) -> str:
        """Place quatre applications en grille 2x2."""
        if len(apps) != 4:
            return "❌ Pour la disposition grille, il faut exactement quatre applications."
        width, height = await self._get_screen_size()
        half_w = width // 2
        half_h = height // 2
        positions = [
            (0, 0),          # haut-gauche
            (half_w, 0),      # haut-droit
            (0, half_h),      # bas-gauche
            (half_w, half_h)  # bas-droit
        ]
        errors = []
        for i, app in enumerate(apps):
            x, y = positions[i]
            await self._activate_app(app)
            await asyncio.sleep(0.5)
            script = f'''
            tell application "System Events"
                tell process "{app}"
                    set position of window 1 to {{{x}, {y}}}
                    set size of window 1 to {{{half_w}, {half_h}}}
                end tell
            end tell
            '''
            success, err = await self._run_applescript(script, timeout=5.0)
            if not success:
                errors.append(f"{app}: {err}")
        if errors:
            return f"⚠️ Disposition partielle : {', '.join(errors)}"
        return f"✅ Fenêtres disposées en grille 2x2."

    async def _tool_arrange_windows(self, layout: str, apps: Optional[List[str]] = None) -> str:
        start = time.time()
        try:
            if layout == "side_by_side":
                if not apps or len(apps) < 2:
                    return "❌ Paramètre 'apps' manquant ou insuffisant pour la disposition côte à côte."
                result = await self._arrange_side_by_side(apps)
            elif layout == "grid_2x2":
                if not apps or len(apps) < 4:
                    return "❌ Paramètre 'apps' manquant ou insuffisant pour la grille 2x2."
                result = await self._arrange_grid_2x2(apps)
            else:
                result = f"❌ Disposition '{layout}' inconnue."
            record_tool_execution(self.name, "arrange_windows", time.time() - start, error=False)
            return result
        except Exception as e:
            logger.error(f"Exception arrange_windows: {e}")
            record_tool_execution(self.name, "arrange_windows", time.time() - start, error=True)
            return f"❌ Erreur: {e}"

    # -----------------------------------------------------------------------
    # Interface de l'agent
    # -----------------------------------------------------------------------
    def can_handle(self, query: str) -> bool:
        return self.can_handle_quick(query) >= 0.5

    def can_handle_quick(self, query: str) -> float:
        q = query.lower()
        score = 0.0

        if any(kw in q for kw in OPEN_KEYWORDS):
            score = max(score, 0.7)
            if any(app in q for app in KNOWN_APPS):
                score = max(score, 0.9)

        if any(kw in q for kw in TYPE_KEYWORDS):
            score = max(score, 0.6)
            if re.search(QUOTE_PATTERN, q):
                score = max(score, 0.85)

        if any(kw in q for kw in CLICK_KEYWORDS):
            score = max(score, 0.5)
            if re.search(COORDS_PATTERN, q):
                score = max(score, 0.8)

        if any(kw in q for kw in SCREENSHOT_KEYWORDS):
            score = max(score, 0.95)

        if any(kw in q for kw in MOVE_KEYWORDS) and re.search(COORDS_PATTERN, q):
            score = max(score, 0.8)

        if any(kw in q for kw in ARRANGE_KEYWORDS):
            score = max(score, 0.7)

        if any(kw in q for kw in MAIL_KEYWORDS):
            score = max(score, 0.7)

        if any(kw in q for kw in SAFARI_KEYWORDS):
            score = max(score, 0.7)

        return score

    async def handle(self, query: str) -> str:
        q = query.lower()

        if any(kw in q for kw in OPEN_KEYWORDS):
            app = self._parse_open_application(query)
            if app:
                return await self._tool_open_application(app_name=app)

        if any(kw in q for kw in TYPE_KEYWORDS):
            text = self._parse_type_text(query)
            if text:
                app_name = next((a for a in NOTES_APPS if a in q), None)
                return await self._tool_type_text(text=text, app_name=app_name)

        if any(kw in q for kw in CLICK_KEYWORDS):
            coords = self._parse_coords(query)
            if coords:
                return await self._tool_click(**coords)
            return "❓ Précise les coordonnées du clic (ex: 'clique à 500, 300')."

        if any(kw in q for kw in SCREENSHOT_KEYWORDS):
            return await self._tool_get_screenshot()

        if any(kw in q for kw in MOVE_KEYWORDS):
            coords = self._parse_coords(query)
            if coords:
                return await self._tool_move_mouse(**coords)
            return "❓ Précise les coordonnées de destination (ex: 'déplace à 800, 400')."

        if any(kw in q for kw in ARRANGE_KEYWORDS):
            layout = None
            if re.search(ARRANGE_PATTERNS["side_by_side"], q, re.IGNORECASE):
                layout = "side_by_side"
            elif re.search(ARRANGE_PATTERNS["grid_2x2"], q, re.IGNORECASE):
                layout = "grid_2x2"
            if layout:
                apps = []
                for app in KNOWN_APPS:
                    if app in q:
                        apps.append(app.capitalize())
                return await self._tool_arrange_windows(layout=layout, apps=apps if apps else None)
            return "❓ Précise la disposition souhaitée (ex: 'côte à côte', 'grille')."

        if any(kw in q for kw in MAIL_KEYWORDS):
            return await super().handle(query)

        if any(kw in q for kw in SAFARI_KEYWORDS):
            url_match = re.search(r'https?://[^\s]+', query)
            if url_match:
                url = url_match.group()
                return await self._tool_safari_open_url(url=url)
            return await super().handle(query)

        return await super().handle(query)

    # -----------------------------------------------------------------------
    # Méthodes de parsing
    # -----------------------------------------------------------------------
    def _parse_open_application(self, query: str) -> Optional[str]:
        for pat in OPEN_PATTERNS:
            match = re.search(pat, query, re.IGNORECASE)
            if match:
                app = match.group(match.lastindex).strip()
                app = re.sub(ARTICLE_PATTERN, "", app, flags=re.IGNORECASE)
                return app.strip()
        return None

    def _parse_type_text(self, query: str) -> Optional[str]:
        match = re.search(QUOTE_PATTERN, query)
        if match:
            return match.group(1)
        for pat in TYPE_PATTERNS:
            match = re.search(pat, query, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _parse_coords(self, query: str) -> Optional[dict]:
        match = re.search(COORDS_PATTERN, query)
        if match:
            return {"x": int(match.group(1)), "y": int(match.group(2))}
        return None