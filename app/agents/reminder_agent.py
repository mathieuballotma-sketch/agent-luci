"""
Agent spécialisé dans la gestion des rappels macOS.
Utilise la validation Pydantic pour les paramètres des outils.
"""

import subprocess
import re
import json
from datetime import datetime
from pydantic import BaseModel, Field
from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger


class ReminderAgentCreateReminderContract(BaseModel):
    title: str = Field(..., description="Titre du rappel")
    date: str = Field(None, description="Date au format YYYY-MM-DD", pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str = Field(None, description="Heure au format HH:MM", pattern=r"^\d{2}:\d{2}$")
    notes: str = Field("", description="Notes ou description supplémentaires")


class ReminderAgent(BaseAgent):
    """Agent spécialisé dans la gestion des rappels macOS."""

    def __init__(self, llm_service, bus, config):
        super().__init__("ReminderAgent", llm_service, bus)
        self.default_list = config.get("reminders_default_list", "Rappels")

    def get_tools(self) -> list:
        return [
            Tool(
                name="create_reminder",
                description="Crée un nouveau rappel dans l'application Rappels macOS",
                contract=ReminderAgentCreateReminderContract,
            )
        ]

    async def _tool_create_reminder(self, title: str, date: str = None, time: str = None, notes: str = "") -> str:
        """Crée un rappel via AppleScript."""
        # Échappement pour AppleScript
        def escape(s):
            return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')

        title_escaped = escape(title)
        notes_escaped = escape(notes)

        # Construction de la clause due date
        due_script = ""
        if date and time:
            try:
                dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                due_script = f"set due date of last reminder to date \"{dt.strftime('%d/%m/%Y %H:%M')}\""
            except:
                due_script = ""
        elif date:
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
                due_script = f"set due date of last reminder to date \"{dt.strftime('%d/%m/%Y')}\""
            except:
                due_script = ""

        # Script principal
        applescript = f"""
tell application "Reminders"
    make new reminder with properties {{name:"{title_escaped}", body:"{notes_escaped}"}}
    {due_script}
end tell
"""
        try:
            result = subprocess.run(['osascript', '-e', applescript], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info(f"Rappel créé : {title}")
                return f"✅ Rappel créé : {title}"
            else:
                logger.error(f"Erreur AppleScript: {result.stderr}")
                return f"Erreur lors de la création du rappel : {result.stderr}"
        except subprocess.TimeoutExpired:
            return "Erreur: Timeout lors de la création du rappel"
        except Exception as e:
            logger.error(f"Erreur ReminderAgent: {e}")
            return f"Erreur : {str(e)}"

    def can_handle(self, query: str) -> bool:
        q = query.lower().strip()
        keywords = [
            "rappel", "reminder", "rappelle", "n'oublie pas", "pense à",
            "mes moi un rappel", "crée un rappel", "ajoute un rappel", "programme un rappel"
        ]
        return any(kw in q for kw in keywords)

    def handle(self, query: str) -> str:
        prompt = f"""
Tu es un assistant qui gère les rappels. Voici la demande : "{query}"
Extrais les informations suivantes au format JSON :
- title : le titre du rappel (ou le texte complet)
- date : la date au format YYYY-MM-DD (si précisée)
- time : l'heure au format HH:MM (si précisée)
- notes : des notes supplémentaires (optionnel)

Si la date ou l'heure ne sont pas précisées, mets null.
Réponds uniquement avec le JSON.
"""
        try:
            response = self.ask_llm(prompt)
            data = self.extract_json_from_response(response)
            if data:
                title = data.get("title", query)
                date = data.get("date")
                time_str = data.get("time")
                notes = data.get("notes", "")
                return self._tool_create_reminder(title=title, date=date, time=time_str, notes=notes)
            else:
                return self._tool_create_reminder(title=query)
        except Exception as e:
            logger.error(f"Erreur dans ReminderAgent.handle: {e}")
            return f"Erreur lors de la création du rappel: {str(e)}"