import subprocess
import shlex
import time
from pathlib import Path
from typing import Optional, Tuple
from ..utils.exceptions import ActionError, AppleScriptError, FileOperationError
from ..utils.logger import get_logger
from ..utils.notifier import send_notification

logger = get_logger(__name__)

class SystemActions:
    """
    Actions système : création de notes, rappels, notifications, ouverture de fichiers.
    """

    def _run_applescript(self, script: str, timeout: int = 15) -> Tuple[bool, str]:
        """
        Exécute un script AppleScript et retourne (succès, sortie/erreur).
        """
        logger.debug(f"Exécution AppleScript : {script[:200]}...")
        try:
            process = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
            if process.returncode == 0:
                logger.debug(f"AppleScript réussi : {process.stdout[:100]}...")
                return True, process.stdout.strip()
            else:
                logger.error(f"AppleScript échoué : {process.stderr}")
                return False, process.stderr
        except subprocess.TimeoutExpired:
            raise AppleScriptError(f"AppleScript a dépassé le timeout de {timeout}s.")
        except Exception as e:
            raise AppleScriptError(f"Erreur inattendue dans AppleScript : {e}")

    def _escape_applescript(self, text: str) -> str:
        """
        Échappe les caractères spéciaux pour AppleScript.
        """
        # Séquence d'échappement : backslash, guillemet, retour à la ligne
        replacements = [
            ('\\', '\\\\'),
            ('"', '\\"'),
            ('\n', '\\n'),
            ('\r', '\\r'),
            ('\t', '\\t'),
        ]
        for old, new in replacements:
            text = text.replace(old, new)
        return text

    def _open_file(self, path: Path) -> bool:
        """
        Ouvre un fichier avec l'application par défaut.
        """
        try:
            # Utiliser la liste d'arguments pour éviter shell=True
            result = subprocess.run(['open', str(path)], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"✅ Fichier ouvert : {path}")
                return True
            else:
                logger.error(f"Erreur à l'ouverture de {path} : {result.stderr}")
                return False
        except Exception as e:
            raise FileOperationError(f"Impossible d'ouvrir le fichier {path} : {e}")

    def create_note(self, title: str, content: str) -> bool:
        """
        Crée une note dans l'application Notes.
        """
        if not title or not content:
            raise ActionError("Le titre et le contenu ne peuvent pas être vides.")
        escaped_title = self._escape_applescript(title)
        escaped_content = self._escape_applescript(content)
        script = f'''
        tell application "Notes"
            make new note with properties {{name:"{escaped_title}", body:"{escaped_content}"}}
        end tell
        '''
        logger.info(f"Tentative de création de la note '{title}'...")
        success, output = self._run_applescript(script)
        if success:
            logger.info(f"✅ Note '{title}' créée.")
            send_notification(title="Note créée", message=f"Note '{title}' ajoutée dans Notes")
            return True
        else:
            raise AppleScriptError(f"Échec création note : {output}")

    def create_reminder(self, name: str, notes: str = "", due_date: Optional[str] = None) -> bool:
        """
        Crée un rappel dans l'application Rappels.
        """
        if not name:
            raise ActionError("Le nom du rappel ne peut pas être vide.")
        escaped_name = self._escape_applescript(name)
        escaped_notes = self._escape_applescript(notes)
        script = f'''
        tell application "Reminders"
            tell default list
                make new reminder with properties {{name:"{escaped_name}", body:"{escaped_notes}"}}
            end tell
        end tell
        '''
        logger.info(f"Tentative de création du rappel '{name}'...")
        success, output = self._run_applescript(script)
        if success:
            logger.info(f"✅ Rappel '{name}' créé.")
            send_notification(title="Rappel créé", message=f"Rappel '{name}' ajouté")
            return True
        else:
            # Fallback sur la liste par défaut "Rappels"
            fallback_script = f'''
            tell application "Reminders"
                tell list "Rappels"
                    make new reminder with properties {{name:"{escaped_name}", body:"{escaped_notes}"}}
                end tell
            end tell
            '''
            logger.warning(f"Premier script échoué, tentative avec liste 'Rappels'...")
            success2, output2 = self._run_applescript(fallback_script)
            if success2:
                logger.info(f"✅ Rappel '{name}' créé (liste Rappels).")
                send_notification(title="Rappel créé", message=f"Rappel '{name}' ajouté")
                return True
            else:
                raise AppleScriptError(f"Échec création rappel : {output} (premier) et {output2} (fallback)")

    def send_notification(self, title: str, message: str) -> bool:
        """
        Envoie une notification système.
        """
        send_notification(title=title, message=message)
        return True

    def open_file(self, path: str) -> bool:
        """
        Ouvre un fichier avec l'application par défaut.
        """
        return self._open_file(Path(path))
