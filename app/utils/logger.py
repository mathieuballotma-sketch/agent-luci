import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

def setup_logger(
    name: str = "agent_lucide",
    level: int = logging.DEBUG,
    log_file: Path = None,
    max_bytes: int = 10_485_760,  # 10 Mo
    backup_count: int = 5
) -> logging.Logger:
    """
    Configure et retourne un logger avec sortie console et éventuellement fichier.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Éviter les doublons de handlers
    if logger.handlers:
        return logger

    # Format détaillé incluant le nom du module et la fonction
    formatter = logging.Formatter(
        '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler fichier (optionnel)
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

# Logger par défaut (sans fichier)
logger = setup_logger()

def get_logger(name: str = None) -> logging.Logger:
    """Retourne un logger avec un nom spécifique (sous-hiérarchie)."""
    if name:
        return logging.getLogger(f"agent_lucide.{name}")
    return logger