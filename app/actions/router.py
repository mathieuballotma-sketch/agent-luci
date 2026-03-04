# app/actions/router.py
import re
from ..utils.logger import logger

class ActionRouter:
    def __init__(self, system_actions, writer_agent):
        self.system = system_actions
        self.writer = writer_agent

    def parse_and_execute(self, response: str):
        lines = response.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('ACTION:'):
                parts = line[7:].split('|')
                action = parts[0].strip()
                params = [p.strip() for p in parts[1:]] if len(parts) > 1 else []
                logger.info(f"🔧 Action détectée : {action} avec paramètres {params}")

                if action == "create_word_document":
                    if len(params) >= 2:
                        result = self.writer.create_word_document(params[0], params[1])
                        return True, result
                    else:
                        return True, "Erreur : paramètres insuffisants pour create_word_document"

                # Autres actions...
                elif action == "create_note":
                    # ...
                    pass
                elif action == "create_reminder":
                    # ...
                    pass

        return False, response