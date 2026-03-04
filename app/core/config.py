"""
Module de configuration pour Agent Lucide.
Utilise des dataclasses pour une structure typée et validée.
Charge la configuration depuis un fichier YAML.
"""

from dataclasses import dataclass, field, asdict
from pathlib import Path
import yaml
from typing import Optional, Dict, Any
from ..utils.exceptions import ConfigError
from ..utils import hardware as hw_utils  # ← alias pour éviter conflit


@dataclass
class AppConfig:
    name: str = "Agent Lucide"
    version: str = "4.0"
    data_dir: Path = Path("./data")
    docs_dir: Path = Path("./Lucid_Docs")
    logs_dir: Path = Path("./logs")


@dataclass
class ModelConfig:
    name: str
    max_tokens: int = 2048
    temperature: float = 0.7


@dataclass
class LLMConfig:
    host: str = "http://localhost:11434"
    default_model: str = "qwen2.5:7b"
    timeout: int = 60
    retry_attempts: int = 2
    retry_delay: float = 1.0
    keep_alive: int = -1
    models: Dict[str, ModelConfig] = field(default_factory=lambda: {
        "speed": ModelConfig("qwen2.5:3b", 512, 0.3),
        "balanced": ModelConfig("qwen2.5:7b", 1024, 0.5),
        "quality": ModelConfig("qwen2.5:14b", 2048, 0.7),
        "sentinel": ModelConfig("qwen2.5:0.5b", 256, 0.1),
    })


@dataclass
class AudioConfig:
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    sample_rate: int = 16000
    language: str = "fr"
    beam_size: int = 5
    temp_dir: Path = Path("./data/temp")
    recording_duration: int = 5
    silence_threshold: float = 0.1


@dataclass
class VisionConfig:
    tesseract_cmd: str = "/opt/homebrew/bin/tesseract"
    use_ocr_fallback: bool = True
    min_text_length: int = 50
    cache_duration: int = 5
    crop_top: int = 100
    crop_bottom: int = 80
    max_chars: int = 3000
    interval: int = 10


@dataclass
class RAGConfig:
    chroma_path: Path = Path("./data/chroma")
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 500
    chunk_overlap: int = 50
    max_sources: int = 5
    persist_directory: str = "./data/chroma"
    collection_name: str = "documents"


@dataclass
class ActionsConfig:
    notes_default_account: bool = True
    reminders_default_list: bool = True
    word_output_dir: Path = Path("./Lucid_Docs")
    allowed_apps: list = field(default_factory=lambda: ["Notes", "Rappels", "Mail"])


@dataclass
class UIColor:
    accent: str = "#007aff"
    success: str = "#30d158"
    warning: str = "#ff9f0a"
    error: str = "#ff453a"
    background_primary: str = "#1c1c1e"
    background_secondary: str = "#2c2c2e"
    background_input: str = "#3a3a3c"


@dataclass
class UIConfig:
    width: int = 480
    height: int = 630
    position_x: int = 100
    position_y: int = 100
    alpha: float = 0.95
    font_family: str = "SF Pro Display"
    font_size: int = 13
    colors: UIColor = field(default_factory=UIColor)


@dataclass
class ApiKeysConfig:
    news_api_key: str = ""
    telegram_bot_token: str = ""


@dataclass
class HardwareConfig:
    profile: str = "unknown"
    chip: str = "unknown"
    ram_gb: int = 0


@dataclass
class MemoryConfig:
    max_episodic: int = 10000
    working_capacity: int = 10
    auto_consolidate: bool = False
    consolidation_interval: int = 3600


@dataclass
class MetricsConfig:
    enabled: bool = False
    port: int = 8001
    memory_interval: int = 60


@dataclass
class ElasticityConfig:
    base_workers: int = 3
    monitor_interval: int = 2
    speed_model: str = "qwen2.5:3b"
    balanced_model: str = "qwen2.5:7b"
    quality_model: str = "qwen2.5:14b"
    sentinel_model: str = "qwen2.5:0.5b"


@dataclass
class TelegramConfig:
    bot_token: str = ""
    webhook_base: str = ""


@dataclass
class Config:
    app: AppConfig = field(default_factory=AppConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    actions: ActionsConfig = field(default_factory=ActionsConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    api_keys: ApiKeysConfig = field(default_factory=ApiKeysConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    elasticity: ElasticityConfig = field(default_factory=ElasticityConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    @classmethod
    def load(cls, path: Optional[Path] = None):
        if path is None:
            path = Path("config.yaml")
        elif isinstance(path, str):
            path = Path(path)

        if not path.exists():
            raise ConfigError(f"Fichier de configuration introuvable : {path}")

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        hw_opt = hw_utils.get_optimized_config()  # ← utilisation de l'alias

        # App
        app_data = data.get('app', {})
        app = AppConfig(
            name=app_data.get('name', 'Agent Lucide'),
            version=app_data.get('version', '4.0'),
            data_dir=Path(app_data.get('data_dir', './data')),
            docs_dir=Path(app_data.get('docs_dir', './Lucid_Docs')),
            logs_dir=Path(app_data.get('logs_dir', './logs')),
        )

        # LLM
        llm_data = data.get('llm', {})
        models_data = llm_data.get('models', {})
        models = {}
        for key, m in models_data.items():
            models[key] = ModelConfig(
                name=m.get('name', f"qwen2.5:{key}"),
                max_tokens=m.get('max_tokens', 2048),
                temperature=m.get('temperature', 0.7),
            )
        if not models:
            models = LLMConfig.models

        llm = LLMConfig(
            host=llm_data.get('host', 'http://localhost:11434'),
            default_model=llm_data.get('default_model', hw_opt['llm']['default_model']),
            timeout=llm_data.get('timeout', 60),
            retry_attempts=llm_data.get('retry_attempts', 2),
            retry_delay=llm_data.get('retry_delay', 1.0),
            keep_alive=llm_data.get('keep_alive', -1),
            models=models,
        )

        # Audio
        audio_data = data.get('audio', {})
        audio = AudioConfig(
            model_size=audio_data.get('model_size', 'small'),
            device=audio_data.get('device', 'cpu'),
            compute_type=audio_data.get('compute_type', 'int8'),
            sample_rate=audio_data.get('sample_rate', 16000),
            language=audio_data.get('language', 'fr'),
            beam_size=audio_data.get('beam_size', 5),
            temp_dir=Path(audio_data.get('temp_dir', './data/temp')),
            recording_duration=audio_data.get('recording_duration', 5),
            silence_threshold=audio_data.get('silence_threshold', 0.1),
        )

        # Vision
        vision_data = data.get('vision', {})
        vision = VisionConfig(
            tesseract_cmd=vision_data.get('tesseract_cmd', '/opt/homebrew/bin/tesseract'),
            use_ocr_fallback=vision_data.get('use_ocr_fallback', True),
            min_text_length=vision_data.get('min_text_length', 50),
            cache_duration=vision_data.get('cache_duration', 5),
            crop_top=vision_data.get('crop_top', 100),
            crop_bottom=vision_data.get('crop_bottom', 80),
            max_chars=vision_data.get('max_chars', 3000),
            interval=vision_data.get('interval', hw_opt['vision']['interval']),
        )

        # RAG
        rag_data = data.get('rag', {})
        rag = RAGConfig(
            chroma_path=Path(rag_data.get('chroma_path', './data/chroma')),
            embedding_model=rag_data.get('embedding_model', 'all-MiniLM-L6-v2'),
            chunk_size=rag_data.get('chunk_size', hw_opt['rag']['chunk_size']),
            chunk_overlap=rag_data.get('chunk_overlap', 50),
            max_sources=rag_data.get('max_sources', 5),
            persist_directory=rag_data.get('persist_directory', './data/chroma'),
            collection_name=rag_data.get('collection_name', 'documents'),
        )

        # Actions
        actions_data = data.get('actions', {})
        actions = ActionsConfig(
            notes_default_account=actions_data.get('notes_default_account', True),
            reminders_default_list=actions_data.get('reminders_default_list', True),
            word_output_dir=Path(actions_data.get('word_output_dir', './Lucid_Docs')),
            allowed_apps=actions_data.get('allowed_apps', ["Notes", "Rappels", "Mail"]),
        )

        # UI
        ui_data = data.get('ui', {})
        colors_data = ui_data.get('colors', {})
        colors = UIColor(
            accent=colors_data.get('accent', '#007aff'),
            success=colors_data.get('success', '#30d158'),
            warning=colors_data.get('warning', '#ff9f0a'),
            error=colors_data.get('error', '#ff453a'),
            background_primary=colors_data.get('background_primary', '#1c1c1e'),
            background_secondary=colors_data.get('background_secondary', '#2c2c2e'),
            background_input=colors_data.get('background_input', '#3a3a3c'),
        )
        ui = UIConfig(
            width=ui_data.get('width', 480),
            height=ui_data.get('height', 630),
            position_x=ui_data.get('position_x', 100),
            position_y=ui_data.get('position_y', 100),
            alpha=ui_data.get('alpha', 0.95),
            font_family=ui_data.get('font_family', 'SF Pro Display'),
            font_size=ui_data.get('font_size', 13),
            colors=colors,
        )

        # Hardware
        hardware_data = data.get('hardware', {})
        hardware = HardwareConfig(
            profile=hw_opt['profile'],
            chip=hw_opt['chip'],
            ram_gb=hw_opt['ram_gb'],
        )

        # API Keys
        api_keys_data = data.get('api_keys', {})
        api_keys = ApiKeysConfig(
            news_api_key=api_keys_data.get('news_api_key', ''),
            telegram_bot_token=api_keys_data.get('telegram_bot_token', ''),
        )

        # Memory
        memory_data = data.get('memory', {})
        memory = MemoryConfig(
            max_episodic=memory_data.get('max_episodic', 10000),
            working_capacity=memory_data.get('working_capacity', 10),
            auto_consolidate=memory_data.get('auto_consolidate', False),
            consolidation_interval=memory_data.get('consolidation_interval', 3600),
        )

        # Metrics
        metrics_data = data.get('metrics', {})
        metrics = MetricsConfig(
            enabled=metrics_data.get('enabled', False),
            port=metrics_data.get('port', 8001),
            memory_interval=metrics_data.get('memory_interval', 60),
        )

        # Elasticity
        elasticity_data = data.get('elasticity', {})
        elasticity = ElasticityConfig(
            base_workers=elasticity_data.get('base_workers', 3),
            monitor_interval=elasticity_data.get('monitor_interval', 2),
            speed_model=elasticity_data.get('speed_model', 'qwen2.5:3b'),
            balanced_model=elasticity_data.get('balanced_model', 'qwen2.5:7b'),
            quality_model=elasticity_data.get('quality_model', 'qwen2.5:14b'),
            sentinel_model=elasticity_data.get('sentinel_model', 'qwen2.5:0.5b'),
        )

        # Telegram
        telegram_data = data.get('telegram', {})
        telegram = TelegramConfig(
            bot_token=telegram_data.get('bot_token', ''),
            webhook_base=telegram_data.get('webhook_base', ''),
        )

        return cls(
            app=app,
            llm=llm,
            audio=audio,
            vision=vision,
            rag=rag,
            actions=actions,
            ui=ui,
            hardware=hardware,
            api_keys=api_keys,
            memory=memory,
            metrics=metrics,
            elasticity=elasticity,
            telegram=telegram,
        )

    def save(self, path: Path = Path("config.yaml")):
        data = {
            "app": asdict(self.app),
            "llm": asdict(self.llm),
            "audio": asdict(self.audio),
            "vision": asdict(self.vision),
            "rag": asdict(self.rag),
            "actions": asdict(self.actions),
            "ui": asdict(self.ui),
            "hardware": asdict(self.hardware),
            "api_keys": asdict(self.api_keys),
            "memory": asdict(self.memory),
            "metrics": asdict(self.metrics),
            "elasticity": asdict(self.elasticity),
            "telegram": asdict(self.telegram),
        }

        def convert_paths(obj):
            if isinstance(obj, dict):
                return {k: convert_paths(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_paths(v) for v in obj]
            elif isinstance(obj, Path):
                return str(obj)
            else:
                return obj

        data = convert_paths(data)

        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def validate(self):
        for d in [self.app.data_dir, self.app.docs_dir, self.app.logs_dir,
                  self.audio.temp_dir, self.rag.chroma_path]:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ConfigError(f"Impossible de créer le dossier {d} : {e}")

        default = self.llm.default_model
        available = [m.name for m in self.llm.models.values()]
        if default not in available:
            raise ConfigError(f"Le modèle par défaut '{default}' n'est pas dans la liste des modèles disponibles : {available}")

        import shutil
        if not shutil.which(self.vision.tesseract_cmd):
            print(f"⚠️ Tesseract introuvable : {self.vision.tesseract_cmd}. Installez-le avec 'brew install tesseract'")

        return True

    def to_dict(self) -> dict:
        return asdict(self)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)