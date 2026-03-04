# app/agents/calendar_agent.py
import datetime
import json
import re
from app.agents.base_agent import BaseAgent, Tool
from app.utils.logger import logger

try:
    import EventKit
    from PyObjCTools import AppHelper
    EKEventStore = EventKit.EKEventStore
    EKEvent = EventKit.EKEvent
    EKAlarm = EventKit.EKAlarm
    EKRecurrenceRule = EventKit.EKRecurrenceRule
    EKRecurrenceEnd = EventKit.EKRecurrenceEnd
    EKWeekday = EventKit.EKWeekday
    EKCalendar = EventKit.EKCalendar
    HAS_EVENTKIT = True
except ImportError:
    HAS_EVENTKIT = False
    logger.error("❌ EventKit non disponible. Installez pyobjc-framework-EventKit")

def datetime_to_nsdate(dt):
    from Foundation import NSDate
    timestamp = dt.timestamp()
    return NSDate.dateWithTimeIntervalSince1970_(timestamp)

def nsdate_to_datetime(nsdate):
    from Foundation import NSDate
    timestamp = nsdate.timeIntervalSince1970()
    return datetime.datetime.fromtimestamp(timestamp)

class CalendarAgent(BaseAgent):
    """
    Agent spécialisé dans la gestion du calendrier macOS (EventKit).
    Peut lire, créer, modifier des événements.
    """

    def __init__(self, llm_service, bus, config):
        super().__init__("CalendarAgent", llm_service, bus)
        self.store = None
        self.default_calendar = None
        if HAS_EVENTKIT:
            self._setup_eventkit()
        else:
            logger.error("CalendarAgent désactivé : EventKit manquant")

    def _setup_eventkit(self):
        self.store = EKEventStore.alloc().init()
        self.store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, lambda granted, error: None)
        import time
        time.sleep(1)
        self.default_calendar = self.store.defaultCalendarForNewEvents()
        logger.info("📅 Agent calendrier initialisé")

    def get_tools(self) -> list:
        return [
            Tool(
                name="list_events",
                description="Liste les événements du calendrier pour une date donnée",
                parameters={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Date au format YYYY-MM-DD ou 'aujourd'hui', 'demain'"
                        }
                    }
                }
            ),
            Tool(
                name="add_event",
                description="Ajoute un événement au calendrier",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Titre de l'événement"},
                        "date": {"type": "string", "description": "Date et heure au format YYYY-MM-DD HH:MM"},
                        "duration": {"type": "integer", "description": "Durée en minutes (défaut: 60)"},
                        "location": {"type": "string", "description": "Lieu (optionnel)"}
                    },
                    "required": ["title", "date"]
                }
            ),
            Tool(
                name="delete_event",
                description="Supprime un événement (par titre)",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Titre de l'événement à supprimer"}
                    },
                    "required": ["title"]
                }
            )
        ]

    def _tool_list_events(self, date: str = "aujourd'hui") -> str:
        return self._list_events(date)

    def _tool_add_event(self, title: str, date: str, duration: int = 60, location: str = "") -> str:
        return self._add_event(title, date, duration, location)

    def _tool_delete_event(self, title: str) -> str:
        return self._delete_event(title)

    def can_handle(self, query: str) -> bool:
        keywords = ["calendrier", "agenda", "rendez-vous", "événement", "event", "calendar", "rdv", "réunion"]
        return any(kw in query.lower() for kw in keywords)

    def handle(self, query: str) -> str:
        # Utilise le LLM pour interpréter la demande et appeler l'outil
        tools_desc = "\n".join([f"- {t.name}: {t.description}" for t in self.get_tools()])
        prompt = f"""
Tu es un assistant qui gère le calendrier. Voici la demande : "{query}"

Outils disponibles:
{tools_desc}

Réponds UNIQUEMENT avec un JSON de la forme:
{{"tool": "nom_outil", "parameters": {{"param1": "valeur1", ...}}}}
Si la demande n'est pas claire, réponds {{"tool": "unknown"}}.
"""
        try:
            response = self.ask_llm(prompt)
            cleaned = response.strip().replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group())
                tool = data.get("tool")
                params = data.get("parameters", {})
                if tool and tool != "unknown":
                    return self.execute_tool(tool, params)
            return "Je n'ai pas compris votre demande concernant le calendrier."
        except Exception as e:
            logger.error(f"Erreur dans CalendarAgent: {e}")
            return f"Erreur lors du traitement: {str(e)}"

    def _list_events(self, date_str: str) -> str:
        if not self.store:
            return "Calendrier non disponible."
        today = datetime.datetime.now()
        if date_str in ["aujourd'hui", "today"]:
            start = datetime.datetime(today.year, today.month, today.day, 0, 0, 0)
            end = start + datetime.timedelta(days=1)
        elif date_str in ["demain", "tomorrow"]:
            start = datetime.datetime(today.year, today.month, today.day, 0, 0, 0) + datetime.timedelta(days=1)
            end = start + datetime.timedelta(days=1)
        else:
            try:
                d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                start = datetime.datetime(d.year, d.month, d.day, 0, 0, 0)
                end = start + datetime.timedelta(days=1)
            except:
                return "Format de date non reconnu."
        start_ns = datetime_to_nsdate(start)
        end_ns = datetime_to_nsdate(end)
        predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(
            start_ns, end_ns, [self.default_calendar]
        )
        events = self.store.eventsMatchingPredicate_(predicate)
        if not events or len(events) == 0:
            return f"Aucun événement trouvé pour {date_str}."
        result = f"Événements pour {date_str} :\n"
        for e in events:
            title = e.title()
            start_date = nsdate_to_datetime(e.startDate()).strftime("%H:%M")
            end_date = nsdate_to_datetime(e.endDate()).strftime("%H:%M")
            location = e.location() or "Pas de lieu"
            result += f"- {title} de {start_date} à {end_date} ({location})\n"
        return result

    def _add_event(self, title: str, date_str: str, duration: int, location: str) -> str:
        if not self.store:
            return "Calendrier non disponible."
        try:
            d = datetime.datetime.fromisoformat(date_str.replace(" ", "T"))
            end = d + datetime.timedelta(minutes=duration)
            event = EKEvent.eventWithEventStore_(self.store)
            event.setTitle_(title)
            event.setStartDate_(datetime_to_nsdate(d))
            event.setEndDate_(datetime_to_nsdate(end))
            if location:
                event.setLocation_(location)
            event.setCalendar_(self.default_calendar)
            success, error = self.store.saveEvent_span_error_(event, 0, None)
            if success:
                logger.info(f"Événement ajouté: {title}")
                return f"✅ Événement '{title}' ajouté le {date_str} pour {duration} minutes."
            else:
                return f"Erreur lors de l'ajout: {error}"
        except Exception as e:
            return f"Erreur de format de date: {str(e)}"

    def _delete_event(self, title: str) -> str:
        if not self.store:
            return "Calendrier non disponible."
        today = datetime.datetime.now()
        start = datetime.datetime(today.year, today.month, today.day, 0, 0, 0)
        end = start + datetime.timedelta(days=30)
        start_ns = datetime_to_nsdate(start)
        end_ns = datetime_to_nsdate(end)
        predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(
            start_ns, end_ns, [self.default_calendar]
        )
        events = self.store.eventsMatchingPredicate_(predicate)
        found = None
        for e in events:
            if e.title() == title:
                found = e
                break
        if not found:
            return f"Aucun événement trouvé avec le titre '{title}' dans les 30 prochains jours."
        success, error = self.store.removeEvent_span_error_(found, 0, None)
        if success:
            return f"✅ Événement '{title}' supprimé."
        else:
            return f"Erreur lors de la suppression: {error}"