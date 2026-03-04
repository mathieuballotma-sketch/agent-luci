🧠 Agent Lucide

Agent IA personnel 100% local, open source et souverain.
Vos données restent sur votre machine. Toujours.


🌱 Un mot honnête avant tout
Ce projet a démarré début février 2025. Il a moins de 2 mois d'existence.
Je suis seul à le développer, brique par brique, en testant chaque composant avant de passer au suivant. La base est là et elle fonctionne — mais soyons clairs : il reste beaucoup de travail. Des bugs existent, certaines fonctionnalités sont encore fragiles, la documentation est incomplète, et l'architecture continue d'évoluer chaque jour.
Je publie ce projet en toute transparence, pas pour impressionner, mais pour construire quelque chose d'utile et d'honnête avec ceux qui partagent cette vision.
Si vous cherchez un outil stable et prêt pour la production — ce n'est pas encore ça.
Si vous voulez suivre la naissance d'un projet ambitieux et y contribuer — vous êtes au bon endroit.

💡 Pourquoi Agent Lucide ?
La plupart des assistants IA vous demandent de confier vos données à un serveur distant. Agent Lucide fait le choix inverse : tout tourne sur votre machine, avec vos propres modèles, sans aucun cloud.
Trois piliers fondateurs :

🔒 Souveraineté totale — 100% local, zéro dépendance cloud, vos données ne quittent jamais votre machine
🤖 Autonomie réelle — L'agent apprend de vos routines, propose des automatisations, et s'améliore en continu
🏪 Extensibilité économique — Une future marketplace permettra à la communauté de créer, partager et vendre ses propres agents


✅ Ce que l'agent sait faire aujourd'hui
Fonctionnalités stables

Interface HUD macOS — Fenêtre translucide flottante, toujours accessible
Contrôle de l'ordinateur — Ouvrir des apps, taper du texte, cliquer, capturer l'écran, gérer les fenêtres
Mémoire — Mémoire de travail (contexte récent) + mémoire épisodique à long terme (ChromaDB)
Recherche d'informations — Web, Wikipedia, arXiv, actualités
Création de documents — Génération de fichiers Word (.docx)
Rappels & Calendrier — Lecture et ajout d'événements macOS
Gestion de fichiers — Lister, copier, déplacer, supprimer

Fonctionnalités expérimentales

StrategistAgent — Propose des automatisations basées sur vos habitudes
Cache de prompts — Cache exact + vectoriel (FAISS) pour accélérer les réponses
Élasticité matérielle — Choix dynamique du modèle LLM selon la charge CPU
ProfileAgent — Analyse vos thèmes récurrents en arrière-plan

Problèmes connus

Latence : 2 à 30 secondes selon la complexité (objectif < 3s en cours)
Certains appels AppleScript peuvent échouer si l'application est mal lancée
La mémoire vectorielle nécessite sentence-transformers — désactivée si absent
Documentation encore très incomplète
Couverture de tests insuffisante


🚀 Vision Future
Agent Lucide n'est pas qu'un assistant — c'est un écosystème d'agents collaboratifs, souverains et auto-améliorants.
DomaineAujourd'huiDemainInterfaceHUD + TelegramCommande vocale, notifications richesActionsOuverture, frappe, clic, emailVérification post-action, zones de sécuritéMémoireÉpisodique + travailMémoire associative, apprentissageAutonomieStrategist basiqueKaizen Agent, renforcementRéseauAucunP2P, calcul distribué, immunité collectiveÉconomieAucuneMarketplace d'agents, SDK développeurs
Ce qui arrive

🛡️ Vérification post-action — L'agent contrôle le résultat de chaque action et corrige si nécessaire
🔄 Kaizen Agent — Analyse les erreurs et propose des correctifs automatiquement
🌐 Réseau P2P — Communication entre agents, partage de puissance de calcul
🏪 Marketplace d'agents — SDK pour créer et vendre des agents spécialisés
🎙️ Commande vocale — Mot déclencheur pour interagir sans les mains


🛠️ Stack technique

Langage — Python 3.11
Modèles LLM — Ollama (qwen2.5 : 0.5b, 3b, 7b, 14b)
Base vectorielle — ChromaDB + FAISS
Interface — PyObjC (Cocoa) pour le HUD macOS
Communication — Bus d'événements asynchrone maison
Métriques — Prometheus


⚙️ Installation
bashgit clone https://github.com/mathieuballotma-sketch/agent-luci.git
cd agent-luci
pip install -r requirements.txt
cp config.yaml.example config.yaml
python main.py
Prérequis : Python 3.11 · Ollama installé et lancé · macOS (optimisé Apple Silicon)

🤝 Contribuer
Le projet est open source (MIT) et ouvert aux contributions.
Que ce soit du code, des retours d'usage ou des idées — vous êtes les bienvenus.

C'est le début. La base est solide. Construisons ensemble.