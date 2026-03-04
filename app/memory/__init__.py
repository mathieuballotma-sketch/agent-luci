"""
Module de mémoire pour Agent Lucide.
Inspiré du cerveau humain : mémoire épisodique (long terme) et mémoire de travail (court terme).
"""

from .episodic_memory import EpisodicMemory
from .working_memory import WorkingMemory
from .memory_service import MemoryService
from .consolidation import ConsolidationEngine

__all__ = ['EpisodicMemory', 'WorkingMemory', 'MemoryService', 'ConsolidationEngine']