#!/usr/bin/env python3
# setup.py - Script d'installation

import os
import sys
import subprocess
import shutil
from pathlib import Path

def check_ollama():
    if not shutil.which("ollama"):
        print("❌ Ollama n'est pas installé. Installez-le depuis https://ollama.com")
        return False
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        if r.status_code == 200:
            print("✅ Ollama est en cours d'exécution.")
            return True
        else:
            print("❌ Ollama ne répond pas. Lancez 'ollama serve'.")
            return False
    except:
        print("❌ Impossible de se connecter à Ollama. Lancez 'ollama serve'.")
        return False

def check_tesseract():
    tesseract_path = shutil.which("tesseract")
    if tesseract_path:
        print(f"✅ Tesseract trouvé : {tesseract_path}")
        return tesseract_path
    else:
        print("❌ Tesseract n'est pas installé. Installez-le avec 'brew install tesseract'")
        return None

def create_dirs():
    dirs = [
        "app/ui",
        "app/core",
        "app/utils",
        "app/services",
        "app/providers",
        "app/brain/neurons",
        "app/brain/synapses",
        "app/actions",
        "app/integrations",
        "data/temp",
        "data/chroma",
        "logs",
        "Lucid_Docs",
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"📁 Dossier créé : {d}")

def create_default_config():
    config_path = Path("config.yaml")
    if config_path.exists():
        print("⚠️ config.yaml existe déjà, on ne l'écrase pas.")
        return
    default_config = """# config.yaml - Configuration par défaut générée par setup.py
app:
  name: "Agent Lucide"
  version: "4.0"
  data_dir: "./data"
  docs_dir: "./Lucid_Docs"
  logs_dir: "./logs"

llm:
  host: "http://localhost:11434"
  default_model: "qwen2.5:7b"
  timeout: 60
  retry_attempts: 2
  retry_delay: 1
  models:
    speed:
      name: "qwen2.5:3b"
      max_tokens: 1024
      temperature: 0.7
    balanced:
      name: "qwen2.5:7b"
      max_tokens: 2048
      temperature: 0.6
    quality:
      name: "qwen2.5:14b"
      max_tokens: 4096
      temperature: 0.5
    sentinel:
      name: "qwen2.5:0.5b"
      max_tokens: 512
      temperature: 0.1

audio:
  model_size: "small"
  device: "cpu"
  compute_type: "int8"
  sample_rate: 16000
  language: "fr"
  beam_size: 5
  temp_dir: "./data/temp"

vision:
  tesseract_cmd: "/opt/homebrew/bin/tesseract"
  crop_top: 100
  crop_bottom: 80
  max_chars: 3000
  interval: 10

rag:
  chroma_path: "./data/chroma"
  embedding_model: "all-MiniLM-L6-v2"
  chunk_size: 500
  chunk_overlap: 50
  max_sources: 5

actions:
  notes_default_account: true
  reminders_default_list: true
  word_output_dir: "./Lucid_Docs"

ui:
  width: 480
  height: 630
  position_x: 100
  position_y: 100
  alpha: 0.95
  font_family: "SF Pro Display"
  font_size: 13
  colors:
    accent: "#007aff"
    success: "#30d158"
    warning: "#ff9f0a"
    error: "#ff453a"
    background_primary: "#1c1c1e"
    background_secondary: "#2c2c2e"
    background_input: "#3a3a3c"
"""
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(default_config)
    print("✅ config.yaml créé avec les valeurs par défaut.")

def install_python_deps():
    print("📦 Installation des dépendances Python...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Dépendances Python installées.")
    except subprocess.CalledProcessError:
        print("❌ Échec de l'installation des dépendances.")
        return False
    return True

def main():
    print("🚀 Préparation de l'environnement pour Agent Lucide...")
    create_dirs()
    tesseract_path = check_tesseract()
    if not tesseract_path:
        print("⚠️ Tesseract est recommandé mais pas obligatoire pour l'instant.")
    ollama_ok = check_ollama()
    if not ollama_ok:
        print("⚠️ Ollama est requis pour le fonctionnement. Installez-le et lancez 'ollama serve'.")
    create_default_config()
    print("✅ Setup terminé. Tu peux maintenant installer les dépendances avec : pip install -r requirements.txt")
    print("   Puis lancer l'agent avec python3 main.py (quand il sera écrit).")

if __name__ == "__main__":
    main()