"""
Hiérarchie des exceptions pour Agent Lucide.
Toutes les exceptions personnalisées héritent de LucidError.
"""

class LucidError(Exception):
    """Exception de base pour toutes les erreurs de l'application."""
    pass

# Erreurs LLM
class LLMError(LucidError):
    """Erreur de base pour les problèmes liés au LLM."""
    pass

class LLMConnectionError(LLMError):
    """Impossible de se connecter au service LLM."""
    pass

class LLMTimeoutError(LLMError):
    """Timeout lors d'un appel LLM."""
    pass

class LLMResponseError(LLMError):
    """Réponse invalide du LLM (format, contenu)."""
    pass

class LLMModelNotFoundError(LLMError):
    """Modèle LLM demandé non disponible."""
    pass

# Erreurs de vision
class VisionError(LucidError):
    """Erreur de base pour le module vision."""
    pass

class TesseractNotFoundError(VisionError):
    """Tesseract OCR non installé ou introuvable."""
    pass

class AccessibilityError(VisionError):
    """Erreur d'accessibilité macOS."""
    pass

# Erreurs audio
class AudioError(LucidError):
    """Erreur de base pour le module audio."""
    pass

class AudioDeviceError(AudioError):
    """Périphérique audio non disponible ou inaccessible."""
    pass

class TranscriptionError(AudioError):
    """Erreur lors de la transcription audio."""
    pass

# Erreurs RAG
class RAGError(LucidError):
    """Erreur de base pour le service RAG."""
    pass

class IndexingError(RAGError):
    """Erreur lors de l'indexation d'un document."""
    pass

# Erreurs d'actions
class ActionError(LucidError):
    """Erreur de base pour l'exécution d'actions système."""
    pass

class AppleScriptError(ActionError):
    """Erreur lors de l'exécution d'un script AppleScript."""
    pass

class FileOperationError(ActionError):
    """Erreur lors d'une opération sur les fichiers."""
    pass

# Erreurs de configuration
class ConfigError(LucidError):
    """Erreur de configuration (fichier manquant, valeur invalide)."""
    pass

# Erreurs de planification
class PlanningError(LucidError):
    """Erreur lors de la génération ou de l'exécution d'un plan."""
    pass

class ToolExecutionError(PlanningError):
    """Erreur lors de l'exécution d'un outil par un agent."""
    pass

class AgentNotFoundError(PlanningError):
    """Agent demandé introuvable."""
    pass