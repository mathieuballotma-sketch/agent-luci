#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import Config
from app.core.engine import LucidEngine

config = Config.load("config.yaml")
engine = LucidEngine(config)

# Test : ouvrir l'application Notes
response, latency = engine.process("Ouvre l'application Notes")
print(f"Réponse : {response}")

# Test : taper du texte (après avoir ouvert Notes manuellement)
response, latency = engine.process("Tape 'Bonjour, je suis Lucie'")
print(f"Réponse : {response}")

engine.stop()