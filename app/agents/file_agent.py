# app/agents/file_agent.py
import os
import shutil
import json
from pathlib import Path
from app.agents.base_agent import BaseAgent
from app.utils.logger import logger

class FileAgent(BaseAgent):
    """
    Agent spécialisé dans la gestion des fichiers et dossiers.
    Peut lister, copier, déplacer, supprimer des fichiers.
    """

    def __init__(self, llm_service, bus, config):
        super().__init__("FileAgent", llm_service, bus)
        self.working_directory = config.get("working_directory", str(Path.home()))
        logger.info(f"📁 Agent fichiers initialisé (dossier de travail: {self.working_directory})")

    def can_handle(self, query: str) -> bool:
        """
        Détecte si la requête concerne des fichiers.
        """
        keywords = ["fichier", "dossier", "copie", "déplace", "supprime", "liste", "renomme", "backup", "sauvegarde"]
        return any(kw in query.lower() for kw in keywords)

    def handle(self, query: str) -> str:
        """
        Point d'entrée principal pour les requêtes en langage naturel.
        Utilise le LLM pour comprendre l'intention et exécuter l'action.
        """
        # 1. Utiliser le LLM pour analyser la demande
        prompt = f"""
Tu es un assistant qui gère des fichiers. Voici la demande de l'utilisateur :
"{query}"

Les actions disponibles sont :
- list : lister les fichiers d'un dossier
- copy : copier un fichier (source, destination)
- move : déplacer un fichier (source, destination)
- delete : supprimer un fichier (chemin)
- rename : renommer un fichier (ancien_nouveau)

Le dossier de travail par défaut est : {self.working_directory}

Réponds UNIQUEMENT avec un JSON de cette forme :
{{
    "action": "nom_action",
    "params": {{
        "param1": "valeur1",
        ...
    }}
}}

Si la demande n'est pas claire, réponds {{"action": "unknown"}}.
"""
        try:
            response = self.ask_llm(prompt)
            # Nettoyer la réponse (enlever les éventuels markdown)
            cleaned = response.strip().replace("```json", "").replace("```", "").strip()
            # Essayer de parser le JSON
            try:
                decision = json.loads(cleaned)
            except json.JSONDecodeError:
                # Si le parsing échoue, on tente d'extraire un JSON avec une regex simple
                import re
                match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if match:
                    decision = json.loads(match.group())
                else:
                    # Fallback : on considère que la réponse est un texte et on essaie de deviner l'action
                    logger.warning(f"Réponse non JSON reçue: {cleaned[:100]}")
                    # On peut essayer une approche basée sur des mots-clés
                    if "liste" in query.lower() or "list" in query.lower():
                        decision = {"action": "list", "params": {}}
                    elif "copie" in query.lower() or "copy" in query.lower():
                        # Extraction basique (à améliorer)
                        decision = {"action": "copy", "params": {"source": "", "destination": ""}}
                    else:
                        return "Désolé, je n'ai pas compris votre demande. Pouvez-vous reformuler ?"
            
            action = decision.get("action")
            params = decision.get("params", {})
            
            if action == "unknown":
                return "Je n'ai pas compris quelle action sur les fichiers vous voulez effectuer."
            
            # Exécuter l'action
            return self.do_action(action, params)
            
        except Exception as e:
            logger.error(f"Erreur dans FileAgent.handle: {e}")
            return f"Erreur lors du traitement: {str(e)}"

    def do_action(self, action: str, params: dict) -> str:
        """
        Exécute une action spécifique avec les paramètres donnés.
        """
        if action == "list":
            return self._list_files(params.get("path", self.working_directory))
        elif action == "copy":
            return self._copy_file(params.get("source"), params.get("destination"))
        elif action == "move":
            return self._move_file(params.get("source"), params.get("destination"))
        elif action == "delete":
            return self._delete_file(params.get("path"))
        elif action == "rename":
            return self._rename_file(params.get("old"), params.get("new"))
        else:
            return f"Action inconnue: {action}"

    def _list_files(self, path: str) -> str:
        """Liste les fichiers d'un dossier."""
        try:
            p = Path(path).expanduser().resolve()
            if not p.exists():
                return f"Le dossier {path} n'existe pas."
            if not p.is_dir():
                return f"{path} n'est pas un dossier."
            
            files = list(p.iterdir())
            if not files:
                return f"Le dossier {path} est vide."
            
            result = f"Contenu de {path}:\n"
            for f in files:
                if f.is_dir():
                    result += f"📁 {f.name}/\n"
                else:
                    size = f.stat().st_size
                    result += f"📄 {f.name} ({size} octets)\n"
            return result
        except Exception as e:
            return f"Erreur lors du listage: {str(e)}"

    def _copy_file(self, source: str, dest: str) -> str:
        """Copie un fichier."""
        try:
            src = Path(source).expanduser().resolve()
            dst = Path(dest).expanduser().resolve()
            
            if not src.exists():
                return f"Le fichier source {source} n'existe pas."
            if src.is_dir():
                return f"La copie de dossiers n'est pas encore supportée."
            
            # Créer le dossier de destination si nécessaire
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(src, dst)
            logger.info(f"Fichier copié: {src} -> {dst}")
            return f"✅ Fichier copié avec succès vers {dest}"
        except Exception as e:
            return f"Erreur lors de la copie: {str(e)}"

    def _move_file(self, source: str, dest: str) -> str:
        """Déplace un fichier."""
        try:
            src = Path(source).expanduser().resolve()
            dst = Path(dest).expanduser().resolve()
            
            if not src.exists():
                return f"Le fichier source {source} n'existe pas."
            
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            logger.info(f"Fichier déplacé: {src} -> {dst}")
            return f"✅ Fichier déplacé avec succès vers {dest}"
        except Exception as e:
            return f"Erreur lors du déplacement: {str(e)}"

    def _delete_file(self, path: str) -> str:
        """Supprime un fichier."""
        try:
            p = Path(path).expanduser().resolve()
            if not p.exists():
                return f"Le fichier {path} n'existe pas."
            if p.is_dir():
                return f"La suppression de dossiers n'est pas autorisée (trop risqué)."
            
            os.remove(p)
            logger.info(f"Fichier supprimé: {p}")
            return f"✅ Fichier supprimé: {path}"
        except Exception as e:
            return f"Erreur lors de la suppression: {str(e)}"

    def _rename_file(self, old: str, new: str) -> str:
        """Renomme un fichier."""
        try:
            old_path = Path(old).expanduser().resolve()
            new_path = Path(new).expanduser().resolve()
            
            if not old_path.exists():
                return f"Le fichier {old} n'existe pas."
            
            old_path.rename(new_path)
            logger.info(f"Fichier renommé: {old} -> {new}")
            return f"✅ Fichier renommé: {new}"
        except Exception as e:
            return f"Erreur lors du renommage: {str(e)}"